
@Library('aws-monitor-lib') _
def dockerRepoOwner = "sm1986"
def githubRepoOwner = "StasX"
def email = "s.mestechkin@gmail.com"
def gitOpsRepo = "argo-gitops"
def currentRepo = "aws-monitor"
def envName = ""
def envShortName = ""
def version = ""
def image = ""
        def appInfo = [:]
podTemplate(cloud: 'kubernetes', containers: [
    containerTemplate(
        name: 'jnlp', 
        image: 'jenkins/inbound-agent:latest'
    ),
    containerTemplate(
        name: 'docker', 
        image: 'docker:26-dind',
        privileged: true,
        args: '--storage-driver=vfs'
    ),
    containerTemplate(
        name: 'alpine', 
        image: 'alpine:latest',
        command: 'sleep', // Don't terminate immediately
        args: '1d'
    ),
    containerTemplate(
        name: 'python', 
        image: 'python:3.13', // Use the latest stable Python image
        command: 'sleep', // Don't terminate immediately
        args: '1d'
    ),
    containerTemplate(
        name: 'helm', 
        image: 'alpine/helm', // Use the latest stable Helm image
        command: 'sleep', // Don't terminate immediately
        args: '1d'
    ), 
    containerTemplate(
        name: 'git', 
        image: 'alpine/git', // Use the latest stable Helm image
        command: 'sleep', // Don't terminate immediately
        args: '1d'
    )], 
  volumes: [
    emptyDirVolume(mountPath: '/var/lib/docker', memory: false)
  ]) {
    node(POD_LABEL) {
        stage('Checkout & Extract App Information') {
            container('jnlp') {
                // select env type
                (envShortName, envName) = envs.choiceEnv()
                // Ensure that work space clean
                cleanWs() 
                // Ensure we skip SSL if needed internally, then pull code
                sh 'git config --global http.sslVerify false'
                checkout scm
                echo "Extracting information from .app-info.json..." 
                def jsonObj = readJSON file: '.app-info.json'
                (appInfo,version,image) = jsons.parse(jsonObj, envShortName)
                if (jsonObj.name != currentRepo){
                    throw Exception("Invalid  information file not match")
                }
            }
        }
        stage('Security Scans') {
            parallel(
                'Bandit Testing': {
                    container('python') {
                        echo "Running Bandit Python Static Analysis..."
                        security.banditScan()
                    }
                },
                'Checkov Testing': {
                    container('python') {
                        echo "Running Checkov on Dockerfile and Helm Chart..."
                        security.checkovScan()
                    }
                },
                'Semgrep Testing': {
                    container('python') {
                        echo "Running Semgrep Scans..."
                        security.semgrepScan()
                    }
                }
            )
        }
        stage('Build Docker Image') {
            container('docker') {
              dockers.build(dockerRepoOwner, image, version)
            }
        }
        stage('Trivy Scan') {
            container('docker') {
                echo "Running Trivy vulnerability scan on the built image..."
                security.trivyScan(dockerRepoOwner, image, version)
            }
        }
        stage('Tag Docker Image') {
            container('docker') {              
                dockers.tag(dockerRepoOwner, image, version)
            }
        }
        stage('Login to Docker repository') {
            container('docker') {              
                dockers.login()
            }
        }
        stage('Push Docker Image') {
            container('docker') {              
                dockers.push(dockerRepoOwner, image, version)
            }
        }
        
        stage('Clone GitOps Repo') {
            container('git') {
                manifests.pull(gitOpsRepo, githubRepoOwner)
            }
        }
        stage('Create Manifest') {
            container('helm') {
                manifests.create(envName, envShortName, gitOpsRepo, appInfo["app_name"], dockerRepoOwner, image, version)
            }
        }
        stage('Push Manifest'){
            container('git'){
                manifests.push ( gitOpsRepo, githubRepoOwner, currentRepo, envName, envShortName, email)
            }
        }
        stage('Change App Version'){
            container('git'){
                echo "Changing ..."
                withCredentials([usernamePassword(credentialsId: 'github_creds', 
                usernameVariable: 'GH_USER', 
                passwordVariable: 'GH_TOKEN')]) {
                    def oldVersion = appInfo["version"]
                    def (major, minor, patch) = oldVersion.tokenize('.')
                    def newPatch = patch.toInteger() + 1
                    def newVersion = "${major}.${minor}.${newPatch}"
                    def name = appInfo['app_name']
                    def description = appInfo['description']
                    withEnv([
                        "GITHUB_REPO_OWNER=${githubRepoOwner}",
                        "CURRENT_REPO=${currentRepo}",
                        "GIT_EMAIL=${email}",
                        "APP_NAME=${appInfo['app_name']}",
                        "APP_DESCRIPTION=${appInfo['description']}",
                        "NEW_VERSION=${newVersion}"
                    ]) {
                        sh '''
                            cat > .app-info.json <<EOF
                            {
                            "name": "$APP_NAME",
                            "version": "$NEW_VERSION",
                            "description": "$APP_DESCRIPTION"
                            }
                            EOF
                            git config user.name "$GH_USER"
                            git config user.email "$GIT_EMAIL"
                            
                            git add .app-info.json
                            git commit -m "Update next app version in .app-info.json"

                            git remote set-url origin https://x-access-token:$GH_TOKEN@github.com/$GITHUB_REPO_OWNER/$CURRENT_REPO.git
                            git push origin main
                        '''
                    }
                }
            }
        }

        stage('Cleanup Workspace') {
            container('alpine') {
                echo "Cleaning up workspace..."
                cleanWs(
                    cleanWhenNotBuilt: true,
                    deleteDirs: true,
                    disableDeferredWipeout: true,
                    notFailBuild: true
                )
            }
        }       
    }

}

