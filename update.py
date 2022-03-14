from ast import arg
from genericpath import exists
from pathlib import Path, PurePath
import json
import os
from posixpath import split
import sys
from threading import local
from typing import Dict, List
import git
from git.index import typ
from git.objects import commit
from git.objects.tag import TagObject
from git.objects.tree import Tree
from git.util import T
import time
import re

# Git globals
local_repo = None
local_head = None
local_branches = None
local_index = None
remote_origin = None
remote_branches = None
remote_commitTagDict: Dict[str, List[str]] = None
remote_branchVerTagDict: Dict[str, str] = None

local_branchVerTagDict: Dict[str, git.objects.tag.TagObjects] = None
local_branch_Nxt_VerTagDict: Dict[str, str] = None
semVerScheme_active: bool = None
semVerScheme_marker:str = "v0.0.0_schemeActive"
verScheme_regex = re.compile("^v[0-9]*\\.[0-9]*\\.[0-9]*_[a-zA-Z0-9]*$")
dir_path: os.path = None
parent_dir_path: os.path = None
main_proj_path: os.path = None




#==================================== Custom Classes ====================================

class SemanticVer:

    def __init__(self, *args):
        if len(args) == 3:
            if (isinstance(args[0], int) and 
                isinstance(args[1], int) and
                isinstance(args[2], int)):
                # if three integers are provided 
                self.major: int = args[0]
                self.minor: int = args[1]
                self.patch: int = args[2]

        elif len(args) == 1:
            if (isinstance(args[0], str)):
                # if a single string is provided 
                # (it is assumed it follows the version Scheme of the program)
                # check that tag has form "v<#>.<#>.<#>_<branchName>"
                if (verScheme_regex.match(args[0])):
                    verNums = re.findall(r'\d+', args[0])
                    if (len(verNums) == 3):
                        self.major: int = int(verNums[0])
                        self.minor: int = int(verNums[1])
                        self.patch: int = int(verNums[2])
                    else: 
                        self.major: int = -1
                        self.minor: int = -1
                        self.patch: int = -1
                
    
    def __str__(self):
        return str(self.major) + "." + str(self.minor) + "." + str(self.patch)
    
    def compare(self, other) -> int:
        if isinstance(other, SemanticVer):
            
            if (self.major == other.major):
                #check next lvl

                if (self.minor == other.minor):
                    #check next lvl

                    if (self.patch == other.patch):
                        return 0

                    elif (self.patch > other.patch):
                        return 1
                    else:
                        return 2

                elif (self.minor > other.minor):
                    return 1
                else:
                    return 2

            elif (self.major > other.major):
                return 1
            else:
                return 2

        else:
            return -1

    def generate_GitTag(self, branchName: str) -> str:
        verTag: str = "v" + str(self.major) + "." + str(self.minor) + "." + str(self.patch) + "_" + branchName
        return verTag

    def inc_Maj(self):
        self.major = self.major + 1
        self.minor = 0
        self.patch = 0

    def inc_Min(self):
        self.minor = self.minor + 1
        self.patch = 0

    def inc_patch(self):
        self.patch = self.patch + 1



class NoRepoTag(Exception):
    pass

class UpdateCancelled(Exception):
    pass
#==============================================================================================================


#==================================== UTILITY FUNCTIONS =======================================================
def get_TagCommitDict_fromRemote(remoteRepo_url: str) -> Dict[str,str]:
    tagCommit_dict: Dict[str, str] = {}

    g = git.cmd.Git()
    blob = g.ls_remote(remoteRepo_url, sort='-v:refname', tags = True)

    blob_lines = blob.split('\n')
    for blob_line in blob_lines:
        split_blob_line = blob_line.split()
        commit = split_blob_line[0]

        tag_unrefined: str = split_blob_line[1].split('/')[-1]
        if (not(tag_unrefined.__contains__('^{}'))):
            continue
        else:
            tag = tag_unrefined.split('^{}')[0]

        tagCommit_dict[tag] = commit
    
    return tagCommit_dict

def get_CommitTagDict_fromRemote(remoteRepo_url: str) -> Dict[str,List[str]]:
    commitTag_dict: Dict[str,List(str)] = {}

    g = git.cmd.Git()
    blob = g.ls_remote(remoteRepo_url, sort='-v:refname', tags=True)

    blob_lines = blob.split('\n')
    for blob_line in blob_lines:
        split_blob_line = blob_line.split()
        commit = split_blob_line[0]
        tag_unrefined: str = split_blob_line[1].split('/')[-1]
        if (not(tag_unrefined.__contains__('^{}'))):
            continue
        else:
            tag = tag_unrefined.split('^{}')[0]
        
        if commit in commitTag_dict:
            commitTag_dict[commit].append(tag)
        else:
            commitTag_dict[commit] = [tag]
    
    return commitTag_dict

def get_BranchLatVerTagDict_fromRemote() -> Dict[str,str]:
    global local_repo
    global remote_commitTagDict

    branchLatVerTag_dict: Dict[str, str] = {}

    for remote_branch in local_repo.remote().refs:
        remote_branch_name = remote_branch.name

        if (remote_branch_name == "origin/HEAD"):
            continue

        remote_verTag_found = False 
        for commit in local_repo.iter_commits(remote_branch_name):
            if (remote_verTag_found):
                break
            if (str(commit) in remote_commitTagDict):

                for tag in remote_commitTagDict[str(commit)]:
                    if (verScheme_regex.match(tag) and tag != semVerScheme_marker):
                        remote_verTag_found = True
                        branchLatVerTag_dict[remote_branch_name] = tag

    return branchLatVerTag_dict

def get_BranchLatVerTagDict_local() -> Dict[str, git.objects.tag.TagObject]:
    global local_repo
    global local_branches

    branchLatVerTag_dict: Dict[str, str] = {}

    for local_branch in local_branches:
        local_branch_name = local_branch.name
        
        # get sorted list of tags in reverse order (original order is oldest to newest - want newest first)
        sorted_tag_refs = sorted(local_repo.tags, key=lambda t: t.commit.committed_datetime, reverse=True)
        latest_tag = None
        for tag_ref in sorted_tag_refs:
            tag_obj = tag_ref.tag
            tag_obj_commit = tag_obj.object
            tag_obj_tagName = tag_obj.tag
            if (tag_obj_commit in local_repo.iter_commits(local_branch_name)):
                if (verScheme_regex.match(tag_obj_tagName) and tag_obj_tagName!= semVerScheme_marker):
                    latest_tag = tag_obj
                    break


        branchLatVerTag_dict[local_branch_name] = latest_tag

    return branchLatVerTag_dict


#============================================================================================================================================

def check_UpdateOp_Fidelity():

    versionH_file = os.path.join(main_proj_path, "version.h")
    if (exists(versionH_file)):

        # retrieve contents of version.h file
        verH_content: List[str] = None
        with open(versionH_file, 'r') as opened_VHF_read:
            verH_content = opened_VHF_read.readlines()

        for verH_rl in verH_content:
            if "FIRMWARE_VERSION" in verH_rl:
                #firmware version data line of version.h file reached
                verH_rl_wrds = verH_rl.split()
                firmware_ver = verH_rl_wrds[2]
                break

        latest_tag_object = local_branchVerTagDict[local_repo.active_branch.name]
        latest_tag_object_name = latest_tag_object.tag

        firmware_semVer = SemanticVer(firmware_ver)
        latest_semVer = SemanticVer(latest_tag_object_name)

        if (firmware_semVer.compare(latest_semVer) == 1):
            # changes were detected by detect_changes.py - i.e. there are changes to push in update
            updateProject(firmware_semVer)
        else:
            print("No changes detected on active branch - nothing to update")
            print("Cancelling update operation...")



def updateProject(nextSemVer: SemanticVer):
    #setup global varibles
    global local_repo 
    global local_head 
    global local_branches
    global local_index
    global remote_origin
    global remote_branches
    global remote_commitTagDict
    global remote_branchVerTagDict
    global local_branchVerTagDict
    global dir_path
    global parent_dir_path
    global main_proj_path

    #setup local variables
    remote_branch_names: list[str] = []
    dest_branch_name: str = None
    dest_branch_name_noOrigDelim: str = None
    ver_tag_mssg: str = None
    stageFiles: list[str] = []

    #begin update operation
    try:

        #prompt user for remote branch to push changes to
        print("Please select from one of the following remote origin branches to push your changes to:")
        for remote_branch in remote_branches:
            remote_branch:git.RemoteReference

            #skip 'HEAD' remote branch
            if (remote_branch.name == 'origin/HEAD'):
                continue
        
            # store the remote branch name to check for valid user selection later
            remote_branch_names.append(remote_branch.name)
            
            # display remote branch name to user
            print(remote_branch.name)

        # retrieve user destination branch selection (reprompt if selection is invalid)
        user_remoteBranch_selectionValid = False
        while(not(user_remoteBranch_selectionValid)):

            user_remoteBranch_selection = input("remote branch selection (enter 'x' to cancel this operation) >> ")

            if (user_remoteBranch_selection == "x"):
                raise UpdateCancelled
            
            if (user_remoteBranch_selection in remote_branch_names):
                print("You have selected a valid remote origin branch to push to")
                dest_branch_name = user_remoteBranch_selection
                dest_branch_name_noOrigDelim = dest_branch_name.split("/")[1]
                user_remoteBranch_selectionValid = True
        
        
        # prompt user for tag message
        ver_tag_mssg = input("Please give a breif description of the changes that have been made in this new version \n" +
            "(enter 'x' to cancel this operation) >>")
        if (ver_tag_mssg == 'x'):
            raise UpdateCancelled
        while (not ver_tag_mssg):
            print("A description of changes must be provided")
            ver_tag_mssg = input("Please give a breif description of the changes that have been made in this new version >>")
            if (ver_tag_mssg == 'x'):
                raise UpdateCancelled

        
        print("Update Summary: ")
        print("=========================================================")

        print("     ", end="") 
        print("Modified files: ")
        print("     ", end="") 
        print("---------------------------------------------------------")
        for diff_item in local_repo.index.diff(None):
            diff_item: git.Diff
            print("     ", end="")
            print("     ", end="")
            print(diff_item.a_path)
            stageFiles.append(str(diff_item.a_path))
        print("     ", end="")
        print("---------------------------------------------------------")

        print("     ", end="") 
        print("New files: ")
        print("     ", end="") 
        print("---------------------------------------------------------")
        for file in local_repo.untracked_files:
            print("     ", end="")
            print("     ", end="")
            print(file)
            stageFiles.append(str(file))
        print("     ", end="")
        print("---------------------------------------------------------")

        # confirm user update
        print("Are you sure you want to update version " + local_branchVerTagDict[local_repo.active_branch.name].tag + " of the project on branch " + dest_branch_name + " to version " + nextSemVer.__str__() + "?")
        user_confirm = input("(y/n) >> ")
        if (user_confirm == "y"):
            print("updating project...")
        else:
            raise UpdateCancelled

        # stage changes for update
        print("Staging changes for update...")
        try:
            local_repo.index.add(stageFiles)
        except OSError:
            print("An error occured while staging files for the update")
            raise UpdateCancelled

        # commit changes for update
        print("Commiting changes for update...")
        commit_mssg = "commiting changes for update to version: " + nextSemVer.__str__()
        local_repo.index.commit(commit_mssg)

        # push changes and update the project from previous version on remote dest. branch
        print("Pushing update to " + dest_branch_name + " @ " + remote_origin.url)
        remote_origin.push(refspec='{}:{}'.format(local_repo.head.ref.name, dest_branch_name_noOrigDelim))

        # update remote so program will be able to see pushed changes locally
        local_repo.remote(name='origin').update()

        # create and push tag to latest commit on remote dest. branch that updates were just pushed to
        update_commit = list(local_repo.iter_commits(dest_branch_name))[0]
        next_ver_tag = local_repo.create_tag(nextSemVer.__str__(), update_commit, ver_tag_mssg)
        remote_origin.push(next_ver_tag)

        # update remote so program will be able to see the newly pushed version tag
        local_repo.remote(name='origin').update()
        
        # update global variables
        remote_commitTagDict = get_CommitTagDict_fromRemote(str(remote_origin.url))
        remote_branchVerTagDict = get_BranchLatVerTagDict_fromRemote()
        local_branchVerTagDict = get_BranchLatVerTagDict_local()

        # give user feedback on success of update operation
        print("project @ " + remote_origin.name + " on branch " + dest_branch_name + " successfully updated to version: " + nextSemVer.__str__())

    except(UpdateCancelled):
        print("Cancelling Update Operation...")
        return 








def initialize():
    #setup global varibles
    global local_repo 
    global local_head 
    global local_branches
    global local_index
    global remote_origin
    global remote_branches
    global remote_commitTagDict
    global remote_branchVerTagDict
    global local_branchVerTagDict
    global dir_path
    global parent_dir_path
    global main_proj_path

    # check for and retrieve command line arguments - program must be provided with the GitHub URL of the remote Git repo being worked with
    # and the root folder name of the project within that repository
    # Ex: 
    #       > python prototype_update_script.py https://github.com/username/repository.git
    if (len(sys.argv) != 3):
        print("Error: Invalid command line arguments - Porgram must be provided with GitHub URL of the remote Git Repository being worked with",end="")
        print(" and the root folder name of the project within that repository \n")
        print("Usage: python prototype_update_script.py <remote Git repo URL> <project root folder name>")
        print("Example: \n \t python prototype_update_script.py https://github.com/<userName>/<repoName>.git MainProgramFolder")
        exit(0)

    # Two command line argument given - appropriate command line arguments given
    user_remoteRepoURL = str(sys.argv[1])
    user_mainProjFolder = str(sys.argv[2])

    # Get directory that program is currently running in
    working_dir_path = os.path.dirname(os.path.realpath(__file__))
    parent_dir_path = os.path.dirname(working_dir_path)
    main_proj_path = os.path.join(parent_dir_path, user_mainProjFolder)

    # search for existing user-desired Git repository in working directory of program 
    # the program will search the working directory in a top-down manner until it finds a folder with .git folder
    # the program will then confirm if this Git repository found has the same remote origin provided by the user at the command line 
    # (i.e. the program will confirm that the local repository found is the one that the user intends to work with)
    repoFound: bool = False
    repoConfirmed: bool = False 
    repoFolderPath: str = None
    for root, dirs, files in os.walk(parent_dir_path):
         if (str(root).endswith('.git')):
            print("Git repository found: " + str(root))
            repoFound = True
            repoFolderPath = root[:-5]
            break;
    if (repoFound):
        # if found, check that it is the one the user intends to work with
        if (user_remoteRepoURL == git.Repo(repoFolderPath).remote(name='origin').url):
            repoConfirmed = True

    #initialize repo object
    if (repoFound and repoConfirmed):
        # repo that user intends to work with has been found in the working directory - synch with repo
        print("The repo you intended to work with has been found in the working directory of the program")
        print("this repo's remote origin lies @: " + str(git.Repo(repoFolderPath).remote(name='origin').url) + " would you like to start working with these repositories?")

        user_choice = input(" (y/n) >> ")
        if (user_choice == 'y'):
            local_repo = git.Repo(repoFolderPath)
        else:
            print("exiting program...")
            exit(0)
        
    else:
        # repo that user intends to work with was not found - raise error
        print("The repo you intended to work with was not found in the working directory of the program")
        print("exiting program...")
        exit(0)

    # initialize remaining global Git variables
    local_head = local_repo.head
    local_branches = local_repo.heads
    local_index = local_repo.index
    remote_origin = local_repo.remote(name='origin')
    remote_branches = local_repo.remote(name='origin').refs

    # update remote
    # NOTE: this will bring down remote tags
    local_repo.remote(name='origin').update()

    #NOTE: update script will immediately begin working with whatever the last active branch of the local repository was
    # this means:
    #   - if the developer did work on branch A but then checked out branch B with no new work done then the next 
    #     this script is run it will not detect the changes made on branch A and will not begin performing update operations
    remote_commitTagDict = get_CommitTagDict_fromRemote(user_remoteRepoURL)
    remote_branchVerTagDict = get_BranchLatVerTagDict_fromRemote()
    local_branchVerTagDict = get_BranchLatVerTagDict_local()


# MAIN PROGRAM FUNCTION
def main():
    initialize()

# PROGRAM EXECUTION STARTING POINT
if __name__ == "__main__":
    main()