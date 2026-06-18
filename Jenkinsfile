
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
        command: 'sleep 1d'
    ),
    containerTemplate(
        name: 'bandit', 
        image: 'python:3.13', // Use the latest stable Python image
        command: 'sleep 1d'
    ),
    containerTemplate(
        name: 'checkov', 
        image: 'python:3.13', // Use the latest stable Python image
        command: 'python3 -m venv .venv; . .venv/bin/activate; pip install checkov; sleep 1d'
    ),
    containerTemplate(
        name: 'semgrep', 
        image: 'python:3.13', // Use the latest stable Python image
        command: 'sleep 1d'
    ),
    containerTemplate(
        name: 'helm', 
        image: 'alpine/helm', // Use the latest stable Helm image
        command: 'sleep 1d'
    ), 
    containerTemplate(
        name: 'kube-score', 
        image: 'zegl/kube-score', // Use the latest stable kube score image
        command: 'sleep 1d'
    ), 
    containerTemplate(
        name: 'git', 
        image: 'alpine/git', // Use the latest stable Helm image
        command: 'sleep 1d'
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
                    container('bandit') {
                        echo "Running Bandit Python Static Analysis..."
                        security.banditScan()
                    }
                },
                'Checkov Testing': {
                    container('checkov') {
                        echo "Running Checkov on Dockerfile and Helm Chart..."
                        security.checkovScan("Dockerfile", "-f", "dockerfile")
                        security.checkovScan("./chart", "-d", "helm", ".venv")
                    }
                },
                'Semgrep Testing': {
                    container('semgrep') {
                        echo "Running Semgrep Scans..."
                        security.semgrepScan()
                    }
                }
            )
        }
        stage('Build Docker Image') {
            container('docker') {
              dockers.build(dockerRepoOwner, image, version, envName, envShortName)
            }
        }
        stage("Run Trivy scan, login to Docker and tag Docker Image"){
            parallel(
                'Trivy Scan' : {
                    container('docker') {
                        echo "Running Trivy vulnerability scan on the built image..."
                        security.trivyScan(dockerRepoOwner, image, version, envName, envShortName)
                    }
                },
                'Tag Docker Image' : {
                    container('docker') {              
                        dockers.tag(dockerRepoOwner, image, version, envName, envShortName)
                    }
                },
                'Login to Docker repository' : {
                    container('docker') {              
                        dockers.login()
                    }
                }           
            )
        }

        stage('Push Docker Image and pull GitOps Repo'){
            parallel(
                'Push Docker Image' : {
                    container('docker') {              
                        dockers.push(dockerRepoOwner, image, version, envName, envShortName)
                    }
                },
                'Pull GitOps Repo' : {
                    container('git') {
                        manifests.pull(gitOpsRepo, githubRepoOwner)
                    }
                }
            )
        }
        stage('Create Manifest') {
            container('helm') {
                manifests.create(envName, envShortName, gitOpsRepo, currentRepo, dockerRepoOwner, image, version)
            }
        }
        stage('Validate Manifest') {
            parallel(
                "Checkov Test" : {
                    container('checkov') {
                        security.checkovScan("./manifests/app.yaml", "-d", "kubernetes", ".venv")
                    }
                },
                "Kube Score Test" : {
                    container('kube-score'){
                        echo "Running kube score test"
                    }
                }
            )
        }
        stage('Push Manifest'){
            container('git'){
                manifests.push ( gitOpsRepo, githubRepoOwner, currentRepo, envName, envShortName, email)
            }
        }
        stage('Change App Version'){
            container('git'){
                echo "Changing version..."
                appInfo["${envShortName}_version"] = versions.bumpUpPatch(version)
                version = appInfo["${envShortName}_version"]
                echo "Updated JSON:"
                echo jsons.stringify(appInfo)
                jsons.saveToJson(appInfo, '.app-info.json')
                config.update(githubRepoOwner, currentRepo, email, version)
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

