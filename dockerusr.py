#!/usr/bin/env python3

# created by Per Arneng 2016

import argparse
import hashlib
import os
import pwd
import subprocess

import sys


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

    def __init__(self, image: str, command: str,
                 usehome: bool, keep_container: bool, keep_script: bool,
                 dry_run: bool):
        self.image = image
        self.command = command
        self.usehome = usehome
        self.keep_container = keep_container
        self.keep_script = keep_script
        self.dry_run = dry_run

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
                                args.keepcontainer, args.keepscript, args.dryrun)


def render_run_script(usr: UserInfo, args: ProgramArguments) -> str:

    home_opts = ""
    if not args.usehome:
        home_opts = "-m -d {u.home_dir}".format(u=usr)

    script_template = """#!/usr/bin/env bash
groupadd -g {u.group_id} {u.user_name}
useradd -u {u.user_id} -g {u.group_id} {home} {u.user_name}
cd /work_dir
sudo -u {u.user_name} HOME={u.home_dir} {a.command}
"""
    return script_template.format(u=usr, a=args, home=home_opts)


def write_run_script(user_info: UserInfo, args: ProgramArguments) -> str:

    script = render_run_script(user_info, args)

    script_name = "dockerusr_run_script_{u.user_name}_{hash}.sh" \
        .format(u=user_info, hash=md5_sum(script))

    full_path = "/tmp/{sn}".format(sn=script_name)

    with open(full_path, "w") as text_file:
        text_file.write(script)

    return script_name


def render_docker_run_command(script_name: str,
                              args: ProgramArguments, cwd: str, usr: UserInfo) -> str:

    home_volume = ""
    if args.usehome:
        home_volume = "-v {u.home_dir}:{u.home_dir}".format(u=usr)

    volumes = "-v /tmp:/t -v {cwd}:/work_dir {hv}".format(cwd=cwd, hv=home_volume)

    rmcontainer = "--rm"
    if args.keep_container:
        rmcontainer = ""

    return "docker run {rm} {volumes} -ti {a.image} /bin/bash /t/{sn}".format(
            a=args, sn=script_name, volumes=volumes, rm=rmcontainer
    )


def main():

    arguments = ProgramArguments.parse(sys.argv)
    user_info = UserInfo.get_user_info()
    working_dir = os.getcwd()
    script_name = write_run_script(user_info, arguments)
    docker_cmd = render_docker_run_command(script_name, arguments, working_dir, user_info)

    if not arguments.dry_run:
        subprocess.call(docker_cmd, shell=True)
    else:
        print(docker_cmd)

    if not arguments.keep_script:
        os.remove("/tmp/{sn}".format(sn=script_name))
    else:
        print("keeping /tmp/{sn}".format(sn=script_name))

if __name__ == "__main__":
    main()
