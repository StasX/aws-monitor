
@Library('aws-monitor-lib') _
def dockerRepoOwner = "sm1986"
def githubRepoOwner = "StasX"
def email = "s.mestechkin@gmail.com"
def gitOpsRepo = "argo-gitops"
def currentRepo = "aws-monitor"
def envType = ""
def envShortType = ""
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
                (envShortType, envType) = envs.choiceEnv()
                // Ensure that work space clean
                cleanWs() 
                // Ensure we skip SSL if needed internally, then pull code
                sh 'git config --global http.sslVerify false'
                checkout scm
                echo "Extracting metadata from .app-info.json..."
                (appInfo,version,image) = jsons.parse('.app-info.json')
                if (appInfo["name"] != currentRepo){
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
              echo "Building docker image..."
              sh "docker build -t docker.io/${dockerRepoOwner}/${appInfo['image_name']}:${appInfo['version']} ."
            }
        }
        stage('Trivy Scan') {
            container('docker') {
                echo "Running Trivy vulnerability scan on the built image..."
                security.trivyScan(String repoOwner, String image, String tag)
            }
        }
        stage('Tag and Push Docker Image') {
            container('docker') {              
              echo "Tagging docker image..."
              sh """
              docker tag \
              docker.io/${dockerRepoOwner}/${appInfo['image_name']}:${appInfo['version']} \
              docker.io/${dockerRepoOwner}/${appInfo['image_name']}:latest
              """
              echo "Logging in to Docker registry..."
              withCredentials([usernamePassword(credentialsId: "dockerhub-creds", usernameVariable: "DOCKERHUB_USERNAME", passwordVariable: "DOCKERHUB_PASSWORD")]) {
                sh "docker login -u ${DOCKERHUB_USERNAME} -p ${DOCKERHUB_PASSWORD} docker.io"
              }
              echo "Pushing docker image to registry..."
              sh "docker push docker.io/${dockerRepoOwner}/${appInfo['image_name']}:${appInfo['version']}"
              sh "docker push  docker.io/${dockerRepoOwner}/${appInfo['image_name']}:latest"

            }
        }
        
        stage('Clone GitOps Repo') {
            container('git') {
                echo "Deploying to Kubernetes using Helm..."
                withEnv([
                    "GITHUB_REPO_OWNER=${githubRepoOwner}",
                    "GITOPS_REPO=${gitOpsRepo}"
                ]) {
                    sh '''
                        git clone https://github.com/$GITHUB_REPO_OWNER/$GITOPS_REPO.git
                    '''
                }
            }
        }
        stage('Create Manifest') {
            container('helm') {
                echo "Prepare HELM manifest for ${envType} environment..."
                def type = ""
                switch(envType){
                    case 'Development' : 
                        type = "dev"
                        break
                    case 'QA' :
                        type = "qa"
                        break
                    case 'Production' :
                        type = "prod"
                        break
                    default :
                        throw new Exception("Invalid  environment")
                }
                sh """                        
                    rm -rf temp && \
                    mkdir temp
                    rm -rf manifests && \
                    mkdir manifests
                    cp chart/* -r temp/
                    cp ${gitOpsRepo}/manifests/${currentRepo}/${type}/values.yaml temp/
                    helm template ${currentRepo} ./temp \
                    --set-string pod.image="${ dockerRepoOwner }/${ appInfo['image_name'] }" \
                    --set-string pod.tag="${ appInfo['version'] }" \
                    --set-string pod.name="${appInfo['app_name']}" \
                    --set secret.enabled=false > manifests/app.yaml
                """
            }
        }
        stage('Push Manifest'){
            container('git'){
                echo "Deploying to ${envType}..."
                def type
                switch(envType){
                    case 'Development' :
                        type = "dev"
                        break
                    case 'QA' :
                        type = "qa"
                        break
                    case 'Production' :
                        type = "prod"
                        break
                    default :
                        throw new Exception("Invalid  environment")
                }
                withCredentials([usernamePassword(credentialsId: 'github_creds', 
                usernameVariable: 'GH_USER', 
                passwordVariable: 'GH_TOKEN')]) {
                    withEnv([
                    "GITHUB_REPO_OWNER=${githubRepoOwner}",
                    "GITOPS_REPO=${gitOpsRepo}",
                    "CURRENT_REPO=${currentRepo}",
                    "ENV_SHORT_TYPE=${type}",
                    "GIT_EMAIL=${email}"
                    ]) {
                        sh '''
                            mv manifests/app.yaml "$GITOPS_REPO/manifests/$CURRENT_REPO/$ENV_SHORT_TYPE/app.yaml"
                            git -C "$GITOPS_REPO" config user.name "$GH_USER"
                            git -C "$GITOPS_REPO" config user.email "$GIT_EMAIL"
                            git -C "$GITOPS_REPO" add manifests/$CURRENT_REPO/$ENV_SHORT_TYPE/app.yaml
                            git -C "$GITOPS_REPO" commit -m "Update application in $ENV_SHORT_TYPE environment"
                            git -C "$GITOPS_REPO" remote set-url origin https://x-access-token:$GH_TOKEN@github.com/$GITHUB_REPO_OWNER/$GITOPS_REPO.git
                            git -C "$GITOPS_REPO" push origin main
                            rm -r temp
                        '''
                    }
                }
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

