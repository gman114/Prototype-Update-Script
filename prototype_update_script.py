from ast import arg
from pathlib import Path, PurePath
import os
import sys
from threading import local
import git
from git.index import typ
from git.objects import commit
from git.objects.tag import TagObject
from git.objects.tree import Tree
from git.util import T
import time
import re

# Git globals
local_repo: git.Repo = None
local_head: git.Head = None
local_branches: git.List[git.Head] = None
local_index = None
remote_origin: git.remote.Remote = None
remote_branches: git.List[git.RemoteReference] = None
remote_commitTagDict: dict[str,str] = None
semVerScheme_active: bool = None
semVerScheme_marker:str = "v0.0.0_schemeActive"
verScheme_regex = re.compile("^v[0-9]*\\.[0-9]*\\.[0-9]*_[a-zA-Z0-9]*$")


def initialize():
    #setup global varibles
    global local_repo 
    global local_head 
    global local_branches
    global local_index
    global remote_origin
    global remote_branches
    global remote_commitTagDict

    # check for and retrieve command line arguments - program must be provided with the GitHub URL of the remote Git repo being worked with
    # Ex: 
    #       > python prototype_update_script.py https://github.com/username/repository.git
    if (len(sys.argv) < 2):
        print("Error: No remote Git repo URL provided - program must be provided with the GitHub URL of the remote Git repository that they wish to work with \n")
        print("Usage: python prototype_update_script.py <remote Git repo URL>")
        print("Example: python prototype_update_script.py https://github.com/<userName>/<repoName>.git")
        exit(0)
    elif (len(sys.argv) > 2):
        print("Error: Too many arguments provided @ command line - program needs only the Github URL of the remote Git repository being worked with \n")
        print("Usage: python prototype_update_script.py <remote Git repo URL>")
        print("Example: python prototype_update_script.py https://github.com/<userName>/<repoName>.git")
        exit(0)

    # One command line argument given - appropriate command line arguments given
    user_remoteRepoURL = str(sys.argv[1])

    # Get directory that program is currently running in
    dir_path = os.path.dirname(os.path.realpath(__file__))
    print(dir_path)

    