// def appname = "hello-newapp"
def repo = "sm1986"
// def appimage = "docker.io/${repo}/${appname}"
// def apptag = "${env.BUILD_NUMBER}"

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
        name: 'ubuntu', 
        image: 'ubuntu:22.04',
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
            container('ubuntu') {
                echo "Extracting metadata from .app-info.json..."
                sh """
                apt-get update && \
                apt-get install -y jq
                """
                
                appInfo["name"] = sh(
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
              sh "docker build -t docker.io/${repo}/${appInfo['image_name']}:${appInfo['version']} ."
            }
        }
        stage('Trivy Scan') {
            container('docker') {
                echo "Running Trivy vulnerability scan on the built image..."
                sh """
                docker run -v /var/run/docker.sock:/var/run/docker.sock \
                aquasec/trivy image ${repo}/${appInfo['image_name']}:${appInfo['version']} \
                --severity HIGH,CRITICAL \
                --exit-code 1
                """
            }
        }
        // stage('Push Docker Image') {
        //     container('docker') {              
        //       echo "Tagging docker image..."
        //       sh "docker tag ${appimage}:${apptag} ${appimage}:latest"

        //       echo "Logging in to Docker registry..."
        //       withCredentials([usernamePassword(credentialsId: "dockerhub-creds", usernameVariable: "DOCKERHUB_USERNAME", passwordVariable: "DOCKERHUB_PASSWORD")]) {
        //         sh "docker login -u ${DOCKERHUB_USERNAME} -p ${DOCKERHUB_PASSWORD} docker.io"
        //       }

        //       echo "Pushing docker image to registry..."
        //       sh "docker push ${appimage}:${apptag}"
        //       sh "docker push  ${appimage}:latest"

        //     }
        // } //end push docker image
        // stage('Helm Template') {
        //     container('helm') {
        //         echo "Deploying to Kubernetes using Helm..."
        //         withCredentials([usernamePassword(credentialsId: "aws-keys", usernameVariable: "AWS_ACCESS_KEY_ID", passwordVariable: "AWS_SECRET_ACCESS_KEY")]) {
        //             sh """
        //               helm template ${appname} ./chart \
        //                 --set env.AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID} \
        //                 --set env.AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
        //               """
        //         }
        //     }
        // }
        stage('Cleanup Workspace') {
            container('jnlp') {
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

