#!/usr/bin/env python3

# Author: Per Arneng
# License: Apache License Version 2.0

import argparse
import hashlib
import os
import pwd
import subprocess
import sys
from abc import abstractmethod, ABCMeta


def md5_sum(plain_text: str):
    md5 = hashlib.md5()
    md5.update(plain_text.encode('utf-8'))
    return md5.hexdigest()


class UserInfo:

    user_name = None  # type: str
    user_id = -1  # type: int
    group_id = -1  # type: int
    home_dir = None  # type: str

    def __init__(self, user_name: str, user_id: int, group_id: int, home_dir: str):
        self.user_name = user_name
        self.user_id = user_id
        self.group_id = group_id
        self.home_dir = home_dir

    def __str__(self):
        return "UserInfo(user_name=%s, user_id=%s, group_id=%s, home_dir=%s)" % \
               (self.user_name, self.user_id, self.group_id, self.home_dir)

    @staticmethod
    def get_user_info():
        user_id = os.getuid()
        group_id = os.getgid()
        user_name = pwd.getpwuid(os.getuid())[0]
        home_dir = pwd.getpwuid(os.getuid())[5]
        return UserInfo(user_name, user_id, group_id, home_dir)


class ProgramArguments:

    command = None  # type: str
    image = None  # type: str
    usehome = False  # type: bool
    keep_container = False  # type: bool
    keep_script = False  # type: bool
    dry_run = False  # type: bool
    container_name = None  # type: str

    def __init__(self, image: str, command: str,
                 usehome: bool, keep_container: bool, keep_script: bool,
                 dry_run: bool, container_name: str):
        self.image = image
        self.command = command
        self.usehome = usehome
        self.keep_container = keep_container
        self.keep_script = keep_script
        self.dry_run = dry_run
        self.container_name = container_name

    @staticmethod
    def parse(argv):

        parser = argparse.ArgumentParser(
                description='launch a docker command as the current user',
                prog='dockerusr'
        )

        parser.add_argument('-i', '--image',
                            help='the docker image to use. defaults to value of $DOCKERUSR_IMAGE', required=False)

        parser.add_argument('-u', '--usehome', action='store_true', default=False,
                            help='mount and use the users home directory', required=False)

        parser.add_argument('-k', '--keepcontainer', action='store_true', default=False,
                            help='do not remove the container after run', required=False)

        parser.add_argument('-s', '--keepscript', action='store_true', default=False,
                            help='do not remove the script after run', required=False)

        parser.add_argument('-d', '--dryrun', action='store_true', default=False,
                            help='do not run docker just output the intent', required=False)
                            
        parser.add_argument('-n', '--containername',
                            help='the name of the container', required=False)


        if '--' not in argv:
            print('need -- delimiter between options and command')
            print('usage: dockerusr <options> -- <command>')
            exit(1)

        if len(argv) < 3:
            print("need more arguments")
            print('usage: dockerusr <options as below> -- <command>')
            parser.print_help()
            exit(1)

        delimiter_index = argv.index('--')
        command = ' '.join(argv[delimiter_index + 1:])

        program_args = argv[1:delimiter_index]


        args = parser.parse_args(program_args)

        if not args.image:
            args.image = os.environ.get('DOCKERUSR_IMAGE')

        if not args.image:
            print("the -i/--image option was not set and no value for $DOCKERUSR_IMAGE")
            exit(1)

        return ProgramArguments(args.image, command, args.usehome,
                                args.keepcontainer, args.keepscript, args.dryrun, args.containername)


class PathInfo:

    tmp = None  # type: str
    cwd = None  # type: str
    tmp_in_container = None  # type: str
    root_in_container = None  # type: str

    def __init__(self):
        self.tmp = "/tmp"
        self.cwd = os.getcwd()
        self.root_in_container = "/host_root"
        self.tmp_in_container = "/host_tmp"


class ScriptRenderer(metaclass=ABCMeta):

    @abstractmethod
    def render(self, usr: UserInfo, args: ProgramArguments, cwd: str) -> str:
        pass

    @abstractmethod
    def get_script_extension(self) -> str:
        pass

    @abstractmethod
    def get_interpreter(self) -> str:
        pass


class BashSudoScriptRenderer(ScriptRenderer):

    def render(self, usr: UserInfo, args: ProgramArguments, path_info: PathInfo) -> str:

        home_opts = ""
        if not args.usehome:
            home_opts = "-m -d {u.home_dir}".format(u=usr)

        script_template = """#!/usr/bin/env bash
groupadd -g {u.group_id} {u.user_name}
useradd -u {u.user_id} -g {u.group_id} {home} {u.user_name}
cd {p.root_in_container}{p.cwd}
sudo -u {u.user_name} HOME={u.home_dir} {a.command}
    """
        return script_template.format(u=usr, a=args,
                                      home=home_opts, p=path_info
        )

    def get_script_extension(self) -> str:
        return 'sh'

    def get_interpreter(self) -> str:
        return '/bin/bash'


def render_script_name(extension: str, username: str, script_content: str) -> str:
    return "dockerusr_run_script_{u}_{hash}.{extension}" \
                .format(u=username, hash=md5_sum(script_content), extension=extension)


def write_to_file(file_path: str, contents: str) -> str:

    with open(file_path, "w") as text_file:
        text_file.write(contents)


def render_docker_run_command(interpreter: str, script_name: str,
                              args: ProgramArguments, usr: UserInfo, path_info: PathInfo) -> str:

    home_volume = ""
    if args.usehome:
        home_volume = "-v {u.home_dir}:{u.home_dir}".format(u=usr)

    volumes = "-v {p.tmp}:{p.tmp_in_container} -v {p.cwd}:{p.root_in_container}{p.cwd} {hv}".format(
                p=path_info, hv=home_volume
    )

    rmcontainer = "--rm"
    if args.keep_container:
        rmcontainer = ""

    container_name = ""
    if args.container_name:
        container_name = "--name {name}".format(name=args.container_name)
        
    return "docker run {name} {rm} {volumes} -ti {a.image} {interpreter} {p.tmp_in_container}/{sn}".format(
            a=args, sn=script_name, volumes=volumes, rm=rmcontainer,
            interpreter=interpreter, p=path_info, name=container_name
    )


def main():

    arguments = ProgramArguments.parse(sys.argv)
    user_info = UserInfo.get_user_info()
    path_info = PathInfo()

    script_renderer = BashSudoScriptRenderer()  # type: ScriptRenderer
    script_contents = script_renderer.render(user_info, arguments, path_info)
    interpreter = script_renderer.get_interpreter()
    extension = script_renderer.get_script_extension()
    script_name = render_script_name(extension, user_info.user_name, script_contents)

    full_script_path = "{tmp}/{sn}".format(tmp=path_info.tmp, sn=script_name)
    write_to_file(full_script_path, script_contents)

    docker_cmd = render_docker_run_command(interpreter, script_name,
                                           arguments, user_info, path_info)

    if not arguments.dry_run:
        subprocess.call(docker_cmd, shell=True)
    else:
        print(docker_cmd)

    if not arguments.keep_script:
        os.remove(full_script_path)
    else:
        print("keeping {s}".format(s=full_script_path))

if __name__ == "__main__":
    main()
