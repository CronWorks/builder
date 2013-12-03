#!/usr/bin/python
from py_base.Job import Job

from os import listdir
from os.path import exists, isdir
import re


class PackageProblemOkToContinue(Exception):
    pass

class Builder(Job):
    APT_PACKAGES_BASE_FILENAME = 'Packages'
    COMMAND_FILTER_NO_EMPTY_LINES = '[^\s]'
    WORKING_DIR_RELATIVE = '.workingDir'
    AUTOMATICALLY_WRITE_CONFIG_FILE = True

    packageList = []
    packageFilesToRemoveBeforeBuilding = ['.svn', 
                                          '.cache', 
                                          '.project', 
                                          '.pydevproject', 
                                          '*.pyc', 
                                          '.DEBUG',
                                          '.git',
                                          'README.md']

    def __init__(self):
        super(Builder, self).__init__()
        self.requireUserConfig('codeSourceDir', str, "Where do you keep your source code?")
        self.requireUserConfig('debsDir', str, "Where do you want to generate .deb files?")

    def doRunSteps(self):
        if self.arguments['all']:
            self.addAllPackagesToList(True)
        elif self.arguments['package']:
            self.packageList.append(self.arguments['package'])
        else:
            # default: build only what's changed
            self.addAllPackagesToList()
        self.buildPackages()
        self.refreshAptRepository()

    def defineCustomArguments(self, parser):
        parser.add_argument('-a',
                            '--all',
                            action='store_true',
                            required=False,
                            default=False,
                            help="Forcibly build all packages (overrides file-update check)",
                            )
        parser.add_argument('-p',
                            '--package',
                            default=None,
                            help="Package name to build",
                            )

    def addAllPackagesToList(self, force=False):
        packages = listdir(self.config['codeSourceDir'])
        packages.sort()
        for package in packages:
            if force or self.needToRebuildPackage(package):
                fullPath = self.config['codeSourceDir'] + '/' + package
                controlFilePath = self.getControlFilePath(package)
                if isdir(fullPath) and exists(controlFilePath):
                    self.packageList.append(package)
            else:
                self.out.put('skipping package "%s" - .deb file already current' % (package))

    def getControlFilePath(self, package):
        return self.getSourceDirFullPath(package) + 'DEBIAN/control'

    def buildPackages(self):
        for package in self.packageList:
            package = re.sub('.deb$', '', package)
            self.out.indent('Building package "%s"' % (package))
            self.buildPackage(package)
            self.out.unIndent()
            self.out.put('done with "%s"' % (package))

    def needToRebuildPackage(self, package):
        debFile = self.getDebFileFullPath(package)
        if not exists(debFile):
            return True
        packageDir = self.getSourceDirFullPath(package)
        # is the package source modified since the deb was last built?
        command = ['find', packageDir, '-type', 'f', '-newer', debFile]  # NOTE: type -f is a workaround for a unison bug. Only file dates are synchronized, but dir dates get updated randomly during each sync.
        result = self.system.runCommand(command, err=None)
        return result != ''

    def buildPackage(self, package):
        try:
            self.incrementPackageVersion(package)
            self.createWorkingDir(package)
            self.buildDebFile(package)
            self.removeWorkingDir()
        except PackageProblemOkToContinue:
            self.out.put('skipping package "%s"' % (package))

    def incrementPackageVersion(self, package):
        path = self.getControlFilePath(package)
        if not exists(path):
            self.out.put('ERROR: no control file found for ' + package)
            raise PackageProblemOkToContinue
        controlFileContent = self.system.readFile(path)
        currentVersionMatch = re.search('(Version: )([\d\.]+\.)(\d+)', controlFileContent)
        currentVersion = currentVersionMatch.group(2) + currentVersionMatch.group(3)
        nextMinorVersionNumber = int(currentVersionMatch.group(3)) + 1
        nextVersion = currentVersionMatch.group(2) + nextMinorVersionNumber.__str__()
        nextVersionText = currentVersionMatch.group(1) + nextVersion
        contentWithNextMinorVersion = re.sub('Version: [\d\.]+',
                                             nextVersionText,
                                             controlFileContent)
        self.out.put('incremented package version from %s to %s' % (currentVersion, nextVersion))
        self.system.writeFile(path, contentWithNextMinorVersion)

    def createWorkingDir(self, package):
        self.out.put('creating working dir')
        workingDirFullPath = self.getWorkingDirFullPath()
        command = ['rsync', '-a', self.getSourceDirFullPath(package), workingDirFullPath]
        self.system.runCommand(command)
        for name in self.packageFilesToRemoveBeforeBuilding:
            command = ['find', workingDirFullPath, '-ignore_readdir_race', '-name', name, '-exec', 'rm', '-rf', '{}', ';']
            self.system.runCommand(command)

    def getSourceDirFullPath(self, package):
        return '%s/%s/' % (self.config['codeSourceDir'], package)

    def getWorkingDirFullPath(self):
        return '%s/%s/' % (self.config['debsDir'], self.WORKING_DIR_RELATIVE)

    def buildDebFile(self, package):
        self.out.indent('building .deb file')
        debFileFullPath = self.getDebFileFullPath(package)
        command = ['rm', '-f', debFileFullPath]
        self.system.runCommand(command)
        command = ['dpkg-deb', '--build', self.getWorkingDirFullPath(), debFileFullPath]
        self.system.runCommand(command, self.config['debsDir'], self.COMMAND_FILTER_NO_EMPTY_LINES)
        self.out.unIndent()

    def getDebFileFullPath(self, package):
        return '%s/%s.deb' % (self.config['debsDir'], package)

    def removeWorkingDir(self):
        self.out.put('cleaning up working directory')
        command = ['rm', '-rf', self.getWorkingDirFullPath()]
        self.system.runCommand(command)

    def refreshAptRepository(self):
        if len(self.packageList) == 0:
            self.out.put('Not rebuilding APT repository metadata (no packages updated)')
        else:
            self.out.put('rebuilding APT repository metadata')
            packageInfoFilename = self.getPackageInfoUncompressedFilename()
            command = ['dpkg-scanpackages', './', '/dev/null']
            # 'None' signals PySystem to throw away stderr.
            packageInfo = self.system.runCommand(command, self.config['debsDir'], err=None, stripNewlines=False)
            self.system.writeFile(packageInfoFilename, packageInfo)
            command = ['gzip', '--best', '--force', packageInfoFilename]
            self.system.runCommand(command)

    def getPackageInfoUncompressedFilename(self):
        return self.config['debsDir'] + '/' + self.APT_PACKAGES_BASE_FILENAME

if __name__ == "__main__":
    from py_base.Job import runMockJob
    runMockJob(Builder)
