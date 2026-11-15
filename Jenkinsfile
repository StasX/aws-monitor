
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

podTemplate(
    cloud: 'kubernetes',
    containers: [
        containerTemplate(
            name: 'jnlp',
            image: 'jenkins/inbound-agent:latest'
        ),
        containerTemplate(
            name: 'docker',
            image: 'docker:26-dind',
            privileged: true,
            // Start dockerd directly: the image entrypoint adds a TCP listener.
            command: 'dockerd',
            args: '--storage-driver=vfs --host=unix:///var/run/docker.sock',
            envVars: [
                envVar(key: 'DOCKER_HOST', value: 'unix:///var/run/docker.sock'),
                envVar(key: 'DOCKER_TLS_CERTDIR', value: ''),
                envVar(key: 'DOCKER_TLS_VERIFY', value: '')
            ]
        ),
        containerTemplate(
            name: 'tests',
            image: 'python:3.14.4-alpine3.23', // Match the application runtime.
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
            command: 'sleep 1d'
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
            name: 'git',
            image: 'alpine/git', // Use the latest stable Helm image
            command: 'sleep 1d'
        )
    ],
    volumes: [
        emptyDirVolume(mountPath: '/var/lib/docker', memory: false)
    ]
) {
    node(POD_LABEL) {
        stage('Docker readiness') {
            container('docker') {
                timeout(time: 1, unit: 'MINUTES') {
                    waitUntil(initialRecurrencePeriod: 1000) {
                        sh(script: 'docker info > /dev/null 2>&1', returnStatus: true) == 0
                    }
                }
            }
        }
        stage('Checkout & Extract App Information') {
            container('jnlp') {                       
                // select env type
                (envShortName, envName) = userInput.choiceEnv()
                // Verify HTTPS certificates even if the agent has a legacy bypass.
                withEnv(['GIT_SSL_NO_VERIFY=false', 'GIT_CONFIG_COUNT=1',
                         'GIT_CONFIG_KEY_0=http.sslVerify', 'GIT_CONFIG_VALUE_0=true']) {
                    if (env.GIT_CA_CREDENTIALS_ID?.trim()) {
                        withCredentials([file(credentialsId: env.GIT_CA_CREDENTIALS_ID.trim(),
                                              variable: 'GIT_SSL_CAINFO')]) {
                            checkout scm
                        }
                    } else {
                        checkout scm
                    }
                }
                echo "Extracting information from .app-info.json..." 
                def jsonObj = readJSON file: '.app-info.json'
                (appInfo,version,image) = jsons.parse(jsonObj, envShortName)
                if (jsonObj.name != currentRepo){
                    userInput.wrongConfiguration()
                }
            }
        }
        stage('Application Tests') {
            container('tests') {
                timeout(time: 10, unit: 'MINUTES') {
                    sh '''
                        set -eu
                        python -m venv /tmp/aws-monitor-tests
                        /tmp/aws-monitor-tests/bin/python -m pip install --no-cache-dir -r requirements.txt
                        /tmp/aws-monitor-tests/bin/python -m unittest discover -s tests -v
                    '''
                }
            }
        }
        stage("Environment preparations"){
            parallel(
                "Install Checkov" : {
                    container('checkov') {
                        // Keep tool dependencies outside the shared workspace.
                        sh '''
                            set -eu
                            python3 -m venv /tmp/aws-monitor-checkov
                            /tmp/aws-monitor-checkov/bin/python -m pip install checkov
                        '''
                    }
                },
                "Install Bandit" : {
                    container('bandit') {
                        installers.installBandit()
                    }
                },
                "Install Semgrep" : {
                    container('semgrep') {
                        sh '''
                            set -eu
                            python3 -m venv /tmp/aws-monitor-semgrep
                            /tmp/aws-monitor-semgrep/bin/python -m pip install semgrep
                        '''
                    }
                },
                "Install Trivy" : {
                    container('docker') {
                        installers.installTrivy()
                    }
                },
                "Install Kube Score" : {
                    container('docker') {
                        installers.installKubeScore()
                    }
                },
            )
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
                        security.checkovScan("Dockerfile", "-f", "dockerfile", "/tmp/aws-monitor-checkov")
                        security.checkovScan("./chart", "-d", "helm", "/tmp/aws-monitor-checkov")
                    }
                },
                'Semgrep Testing': {
                    container('semgrep') {
                        echo "Running Semgrep Scans..."
                        sh '''
                            /tmp/aws-monitor-semgrep/bin/semgrep scan \\
                                --config=p/python \\
                                --config=p/dockerfile \\
                                --config=p/kubernetes \\
                                --config=p/github-actions \\
                                --metrics=off \\
                                --error
                        '''
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
                        security.trivyScanImage(dockerRepoOwner, image, version, envName, envShortName)
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
                        manifests.pull(gitOpsRepo, githubRepoOwner, "monitor")
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
            def manifestPath = "${pwd()}/manifests"
            parallel(
                "Checkov Test" : {
                    container('checkov') {
                        security.checkovScan("./manifests/app.yaml", "-f", "kubernetes", "/tmp/aws-monitor-checkov")
                    }
                },
                "Kube Score Scan" : {
                    container('docker'){
                        echo "Running kube score vulnerability scan on manifest"
                        security.kubeScoreScan(manifestPath, "app.yaml")
                    }
                },
                "Trivy Scan" : {
                    container('docker'){
                        echo "Running trivy vulnerability scan on manifest"
                        security.trivyScanFile(manifestPath, "app.yaml")
                    }
                }
            )
        }
        stage('Push Manifest'){
            container('git'){
                manifests.pull(gitOpsRepo, githubRepoOwner, "main")
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
                utils.updateVersion(githubRepoOwner, currentRepo, email, version)
            }
        }

    }

}

