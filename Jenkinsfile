def dockerRepoOwner = "sm1986"
def githubRepoOwner = "StasX"
def email = "s.mestechkin@gmail.com"
def gitOpsRepo = "argo-gitops"
def currentRepo = "HELM-Exam"

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
        def appInfo = [:]// Define shared map for extracted app information across stages
        stage('Checkout & Extract App Information') {
            container('jnlp') {
                // Ensure that work space clean
                cleanWs() 
                // Ensure we skip SSL if needed internally, then pull code
                sh 'git config --global http.sslVerify false'
                checkout scm
            }
            container('alpine') {
                echo "Extracting metadata from .app-info.json..."
                sh  "apk add --no-cache jq"
                
                appInfo["app_name"] = sh(
                    script: "jq -r '.name' .app-info.json",
                    returnStdout: true
                ).trim()
                appInfo["image_name"] = sh(
                    script: "jq -r '.name' .app-info.json | tr '[:upper:]' '[:lower:]'",
                    returnStdout: true
                ).trim()
                appInfo["version"] = sh(
                    script: "jq -r '.version' .app-info.json",
                    returnStdout: true
                ).trim()
                appInfo["description"] = sh(
                    script: "jq -r '.description' .app-info.json",
                    returnStdout: true
                ).trim()
            }
        }
        stage('Security Scans') {
            parallel(
                'Bandit Testing': {
                    container('python') {
                        echo "Running Bandit Python Static Analysis..."
                        sh """
                        pip install --user bandit
                        
                        python -m bandit -r ./ -x ./.venv,./venv
                        """
                    }
                },
                'Checkov Testing': {
                    container('python') {
                        echo "Running Checkov on Dockerfile and Helm Chart..."
                        sh """
                        python3 -m venv .venv
                        . .venv/bin/activate
                        pip install checkov
                        .venv/bin/python -m checkov.main -f Dockerfile --framework dockerfile
                        .venv/bin/python -m checkov.main -d ./chart --framework helm
                        """
                    }
                },
                'Semgrep Testing': {
                    container('python') {
                        echo "Running Semgrep Scans..."
                        sh """
                        python3 -m venv .venv
                        . .venv/bin/activate
                        .venv/bin/python -m pip install semgrep
                        .venv/bin/semgrep scan \
                        --config=p/python \
                        --config=p/dockerfile \
                        --config=p/kubernetes \
                        --config=p/github-actions \
                        --metrics=off \
                        --error
                        """
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
                sh """
                docker run -v /var/run/docker.sock:/var/run/docker.sock \
                aquasec/trivy image ${dockerRepoOwner}/${appInfo['image_name']}:${appInfo['version']} \
                --severity HIGH,CRITICAL \
                --exit-code 1
                """
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
        stage('Helm Template') {
            container('helm') {
                echo "Deploying to Kubernetes using Helm..."
                sh """
                    mkdir temp
                    helm template test ./chart \
                    --set-string pod.image="${ dockerRepoOwner }/${ appInfo['image_name'] }" \
                    --set-string pod.tag="${ appInfo['version'] }" \
                    --set-string pod.name="${appInfo['app_name']}" \
                    --set secret.enabled=false > temp/application.yaml
                    """
            }
        }
        stage('Push template'){
            container('git'){
                echo "Deploying..."
                withCredentials([usernamePassword(credentialsId: 'github_creds', 
                usernameVariable: 'GH_USER', 
                passwordVariable: 'GH_TOKEN')]) {
                    sh '''
                        git config user.name "${GH_USER}"
                        git config user.email "${email}"
                        git clone https://github.com/${githubRepoOwner}/${gitOpsRepo}.git
                        mv temp/application.yaml argo-gitops/application.yaml

                        git -C ${gitOpsRepo} add application.yaml
                        git -C ${gitOpsRepo} commit -m "Update application.yaml"
                        git -C ${gitOpsRepo} remote set-url origin https://${GH_USER}:${GH_TOKEN}@github.com/${githubRepoOwner}/${gitOpsRepo}.git
                        git -C ${gitOpsRepo} push origin main --force
                    '''
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
                    def (major, minor, patch) = oldVersion.split(".")
                    def newPatch = patch.toInteger() + 1
                    def newVersion = "${major}.${minor}.${newPatch}"
                    sh '''
                        cat <<EOF > .app-info.json
                        {
                            "name": "${ appInfo['app_name'] }",
                            "version": "${newVersion}",
                            "description": "${appInfo['description']}"
                        }
                        EOF
                        git config user.name "${GH_USER}"
                        git config user.email "${email}"

                        git add .app-info.json
                        git commit -m "Update next app version in .app-info.json"
                        git remote set-url origin https://${GH_USER}:${GH_TOKEN}@github.com/${githubRepoOwner}/${currentRepo}.git
                        git push origin main --force
                    '''
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

