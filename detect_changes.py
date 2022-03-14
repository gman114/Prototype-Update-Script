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
working_dir_path: os.path = None
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

def detectCreate_versioningScheme():
    # setup global variables
    global local_repo
    global local_head 
    global local_branches
    global local_index
    global remote_origin
    global remote_branches
    global remote_commitTagDict
    global remote_branchVerTagDict
    global semVerScheme_active

    # check for versioning scheme indicator tag
    verSchemeTag_found = False
    initial_commit = list(local_repo.iter_commits())[-1]
    for tag in local_repo.tags:
        if tag.object.object != initial_commit:
            # only looking for tags pointing to initial commit of repository as this is where the semVerScheme_marker tag will be
            # if the semantic versioning scheme the program follows is established in repository
            continue
        else:
            # found tag pointing to initial commit
            if tag.object.tag == semVerScheme_marker:
                # tag pointing to initial commit is versioning scheme indicator tag - versioning scheme indicator tag found 
                verSchemeTag_found = True
            
            break
            
    if verSchemeTag_found:
        semVerScheme_active = True
    else:
        # the semantic versioning scheme is currently not in place on this repository (both local and remote)

        # create and push versioning scheme indicator tag
        verScheme_indTag_name = "v0.0.0_schemeActive"
        initial_commit = list(local_repo.iter_commits())[-1]
        verScheme_indTag_mssg = "semantic versioning Git tag scheme is active on this repo"
        verScheme_indTag = local_repo.create_tag(verScheme_indTag_name, initial_commit, verScheme_indTag_mssg)
        remote_origin.push(verScheme_indTag)

        # create and push intial version tag v0.1.0
        initial_verTag_name = "v0.1.0_"+local_repo.active_branch.name
        initial_verTag_mssg = "Initial version 0.1.0"
        initial_verTag = local_repo.create_tag(initial_verTag_name, initial_commit, initial_verTag_mssg)
        remote_origin.push(initial_verTag)

        # update remote so program will be able to see the newly pushed version tag
        local_repo.remote(name='origin').update()


        # add code block here to create/update version.h file to contain and reflect initail versioning scheme information
        versionH_file = os.path.join(main_proj_path, "version.h")
        try:
            with open(versionH_file, 'x+') as open_versionH_file:
                open_versionH_file.write("#ifndef VERSION_H\r\n#define VERSION_H\r\n\r\n#define FIRMWARE_VERSION \"0.1.0\"\r\n\r\n#endif")

        except (FileExistsError):

            #DEVELOPERS NOTE: will probably want to chagne the way this exception is handled in the future
            # but this will do for now
            print("Error: a version.h file was already found in the main project")
            print("exiting program")
            exit(0)
        

#============================================================================================================================================

def detectChanges():
    global local_repo
    global local_branchNxtVerTagDict
    global parent_dir_path

    # setup local variables
    chng_in_wrkingTr = False
    chng_in_Index = False
    maj_change: bool = False
    min_change: bool = False
    patch_change: bool = False

    firmware_ver: str = None

    if ( not(not(list(local_repo.index.diff(None)))) ):
        chng_in_wrkingTr = True

    if ( not(not(list(local_repo.index.diff(local_repo.head.commit))))):
        chng_in_Index = True

    if (chng_in_Index or chng_in_wrkingTr):
        # changes on active branch detected
        print("Changes on active branch detected")

        # record change data in version.h file
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

            if (firmware_ver == latest_tag_object_name):
                # changes not previously detected
                print("These changes have not been previously detected")

                changeType_valid = False
                while(not(changeType_valid)):
                    changeType = input("Are these changes \n (M) - Major \n (m) - minor \n (p) - patch \n >> ")
                    if changeType == 'M':
                        maj_change = True
                        changeType_valid = True
                    elif changeType == 'm':
                        min_change = True
                        changeType_valid = True
                    elif changeType == 'p':
                        patch_change = True
                        changeType_valid = True
                    else:
                        print("Invalid change type code provided, please enter M - Major, m - minor or p - patch")

                nxt_ver = SemanticVer(latest_tag_object_name)
                if (maj_change):
                    nxt_ver.inc_Maj()
                elif (min_change):
                    nxt_ver.inc_Min()
                elif (patch_change):
                    nxt_ver.inc_patch()

                # modify retrieved contents of version.h file with updated semantic version number
                for verH_rl in verH_content:
                    if "FIRMWARE_VERSION" in verH_rl:
                        #firmware version data line of version.h file reached
                        verH_rl_wrds = verH_rl.split()
                        verH_rl_wrds[2] = nxt_ver.__str__()
                        verH_rl = ''.join(verH_rl_wrds)
                
                # overwrite version.h file old content with modified content 
                with open(versionH_file, 'w') as opened_VHF_write:
                    opened_VHF_write.writelines(verH_content)
                
            else:
                print("Changes have been previously detected")
        else:
            # version_h file should exist at this point in program exection, so if it doesn't then something's wrong
            pass
    else:
        print("No changes on active branch detected")








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
    global working_dir_path
    global parent_dir_path
    global main_proj_path

    #DEVELOPERS NOTE: I plan to change the command line argument input scheme here to just require the GitHub URL of the repo being worked with
    # (the program will then find the root folder of the main project within the repo on its own) but this is just easier for now while I get core functionality
    # of the program working

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
        # repo that user intends to work with was not found - create local clone of repo
        print("The repo you intended to work with was not found in the working directory of the program")
        print("would you like to create a local clone of the remote repository @: " + str(sys.argv[1]) + " ?")
        
        user_choice = input(" (y/n) >> ")
        if (user_choice == 'y'):
            # repo will be cloned to new subdirectory of same name as repo within same working directory as program
            newFolderName = user_remoteRepoURL.split('/')[-1].split('.')[0]
            localRepoClone_filePath = os.path.join(working_dir_path, newFolderName)
            local_repo = git.Repo.clone_from(user_remoteRepoURL,
                    localRepoClone_filePath,
                    branch='main')
        else:
            print("exiting program...")
            exit(0)

    # initialize remaining global Git variables
    local_head = local_repo.head
    local_branches = local_repo.heads
    local_index = local_repo.index
    remote_origin = local_repo.remote(name='origin')
    remote_branches = local_repo.remote(name='origin').refs

    # update remote
    # NOTE: this is getting remote tags as well
    local_repo.remote(name='origin').update()

    # check to see if the semantic versioning scheme of program is in place
    # initialize versioning scheme if it is not
    detectCreate_versioningScheme()

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






















#JUNK CODE
# os.path.dirname(os.path.realpath(__file__))
# os.path.abspath(os.path.join(os.getcwd(), os.pardir))
# DEBUGGING ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# print("The update script is running in directory: " + dir_path)
# print("The parent directory of the update script is " + parent_dir_path)

'''def detectChanges_OLD():
    global local_repo
    global local_branchNxtVerTagDict
    global parent_dir_path

    # setup local variables
    json_verObject
    maj_change: bool = False
    min_change: bool = False
    patch_change: bool = False

    if ( not(not(list(local_repo.index.diff(None)))) ):
        # changes on active branch detected
        print("Changes on active branch detected")

        # record change data in json file if not already recorded

        # check if json file exists
        version_file = os.path.join(parent_dir_path, "version.json")
        if (exists(version_file)):
            
            # retrieve json version object
            with open(version_file, 'r') as open_verFile:
                json_verObject = json.load(open_verFile)

            if not(local_repo.active_branch.name in json_verObject):
                # changes are being detected for the first time

                print("These changes have not been previously detected")

                changeType_valid = False
                while(not(changeType_valid)):
                    changeType = input("Are these changes \n (M) - Major \n (m) - minor \n (p) - patch \n >> ")
                    if changeType == 'M':
                        maj_change = True
                        changeType_valid = True
                    elif changeType == 'm':
                        min_change = True
                        changeType_valid = True
                    elif changeType == 'p':
                        patch_change = True
                        changeType_valid = True
                    else:
                        print("Invalid change type code provided, please enter M - Major, m - minor or p - patch")

                # create JSON object
                latest_tag = local_branchVerTagDict[local_repo.active_branch.name]
                nxt_ver = SemanticVer(latest_tag)
                if (maj_change):
                    nxt_ver.inc_Maj()
                elif (min_change):
                    nxt_ver.inc_Min()
                elif (patch_change):
                    nxt_ver.inc_patch()

                json_nxtVerObj = {local_repo.active_branch.name : nxt_ver.__str__()}

                with open(version_file, 'w') as open_verFile:
                    json.dump(json_nxtVerObj, open_verFile)

            else:
                # changes have already been detected 

                print("Changes have been previously detected")

    else:
        # no new work detected on active branch
        print("No changes on active branch detected")'''
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~