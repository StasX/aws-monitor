
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

// Capture tool output without requiring Bash/pipefail in Alpine containers.
// Only non-secret test/scan commands go through this helper.
def reportCommand(String reportPath, String command) {
    withEnv(["REPORT_PATH=${reportPath}", "REPORT_COMMAND=${command}"]) {
        sh '''
            set -eu
            mkdir -p reports
            status=0
            sh -ec "$REPORT_COMMAND" > "$REPORT_PATH" 2>&1 || status=$?
            cat "$REPORT_PATH"
            exit "$status"
        '''
    }
}

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
        try {
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
                    reportCommand('reports/application-tests.txt', '''
                        set -eu
                        python -m venv /tmp/aws-monitor-tests
                        /tmp/aws-monitor-tests/bin/python -m pip install --no-cache-dir -r requirements.txt
                        /tmp/aws-monitor-tests/bin/python -m unittest discover -s tests -v
                    ''')
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
            container('docker') {
                withEnv(["CI_IMAGE=${dockerRepoOwner}/${image}:latest"]) {
                    sh '''
                        set -eu
                        mkdir -p reports
                        digest=$(docker buildx imagetools inspect "$CI_IMAGE" --format '{{.Manifest.Digest}}')
                        printf '%s\n' "$digest" | grep -Eq '^sha256:[a-f0-9]{64}$'
                        printf 'pod:\\n  digest: %s\\n' "$digest" > reports/ci-values.yaml
                    '''
                }
            }
            container('helm') {
                sh '''
                    mkdir -p reports
                    helm template aws-monitor chart --namespace ci -f reports/ci-values.yaml > reports/chart.yaml
                '''
            }
            parallel(
                'Bandit Testing': {
                    container('bandit') {
                        echo "Running Bandit Python Static Analysis..."
                        reportCommand('reports/bandit.txt',
                            'python -m bandit -r ./ -x ./.venv,./venv')
                    }
                },
                'Checkov Testing': {
                    container('checkov') {
                        echo "Running Checkov on Dockerfile and Helm Chart..."
                        reportCommand('reports/checkov-dockerfile.txt',
                            '/tmp/aws-monitor-checkov/bin/python -m checkov.main -f Dockerfile --framework dockerfile')
                        reportCommand('reports/checkov-helm.txt',
                            '/tmp/aws-monitor-checkov/bin/python -m checkov.main -f reports/chart.yaml --framework kubernetes')
                    }
                },
                'Semgrep Testing': {
                    container('semgrep') {
                        echo "Running Semgrep Scans..."
                        reportCommand('reports/semgrep.txt', '''
                            /tmp/aws-monitor-semgrep/bin/semgrep scan \\
                                --config=p/python \\
                                --config=p/dockerfile \\
                                --config=p/kubernetes \\
                                --config=p/github-actions \\
                                --metrics=off \\
                                --error
                        ''')
                    }
                }
            )
        }
        stage('Build Docker Image') {
            container('docker') {
                def buildTag = envName == 'Production' ? version : "${version}-${envShortName}"
                withEnv(["BUILD_IMAGE=docker.io/${dockerRepoOwner}/${image}:${buildTag}"]) {
                    reportCommand('reports/docker-build.txt', 'docker build -t "$BUILD_IMAGE" .')
                }
            }
        }
        stage("Run Trivy scan, login to Docker and tag Docker Image"){
            parallel(
                'Trivy Scan' : {
                    container('docker') {
                        echo "Running Trivy vulnerability scan on the built image..."
                        def scanTag = envName == 'Production' ? version : "${version}-${envShortName}"
                        withEnv(["SCAN_IMAGE=${dockerRepoOwner}/${image}:${scanTag}"]) {
                            reportCommand('reports/trivy-image.txt', '''
                                docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
                                    aquasec/trivy image "$SCAN_IMAGE" --severity HIGH,CRITICAL --exit-code 1
                            ''')
                        }
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
            def releaseTag = envName == 'Production' ? version : "${version}-${envShortName}"
            def imageDigest
            container('docker') {
                withEnv(["RELEASE_IMAGE=${dockerRepoOwner}/${image}:${releaseTag}"]) {
                    def reference = sh(script: '''docker image inspect --format '{{index .RepoDigests 0}}' "$RELEASE_IMAGE"''',
                                       returnStdout: true).trim()
                    imageDigest = reference.tokenize('@').last()
                    if (!(imageDigest ==~ /sha256:[a-f0-9]{64}/)) {
                        error('Published image has no valid registry digest')
                    }
                    writeFile file: 'reports/image-reference.txt', text: "${reference}\n"
                }
            }
            container('helm') {
                withEnv(["RELEASE_ENV=${envShortName}", "VALUES_REPO=${gitOpsRepo}",
                         "RELEASE_IMAGE=${dockerRepoOwner}/${image}", "RELEASE_TAG=${releaseTag}",
                         "RELEASE_DIGEST=${imageDigest}"]) {
                    sh '''
                        set -eu
                        mkdir -p manifests
                        helm template aws-monitor chart --namespace "$RELEASE_ENV" \
                            -f "$VALUES_REPO/$RELEASE_ENV/values.yaml" \
                            --set-string "pod.image=$RELEASE_IMAGE" \
                            --set-string "pod.tag=$RELEASE_TAG" \
                            --set-string "pod.digest=$RELEASE_DIGEST" > manifests/app.yaml
                    '''
                }
            }
        }
        stage('Validate Manifest') {
            def manifestPath = "${pwd()}/manifests"
            parallel(
                "Checkov Test" : {
                    container('checkov') {
                        reportCommand('reports/checkov-manifest.txt',
                            '/tmp/aws-monitor-checkov/bin/python -m checkov.main -f ./manifests/app.yaml --framework kubernetes')
                    }
                },
                "Kube Score Scan" : {
                    container('docker'){
                        echo "Running kube score vulnerability scan on manifest"
                        withEnv(["SCAN_PATH=${manifestPath}"]) {
                            reportCommand('reports/kube-score.txt', '''
                                docker run --rm -v "$SCAN_PATH:/work" \
                                    zegl/kube-score:latest score /work/app.yaml
                            ''')
                        }
                    }
                },
                "Trivy Scan" : {
                    container('docker'){
                        echo "Running trivy vulnerability scan on manifest"
                        withEnv(["SCAN_PATH=${manifestPath}"]) {
                            reportCommand('reports/trivy-manifest.txt', '''
                                docker run --rm -v "$SCAN_PATH:/work" -w /work \
                                    aquasec/trivy:latest config app.yaml --severity HIGH,CRITICAL --exit-code 1
                            ''')
                        }
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
        } finally {
            stage('Archive Artifacts') {
                archiveArtifacts artifacts: 'reports/**/*.txt,reports/ci-values.yaml,manifests/app.yaml',
                    allowEmptyArchive: true, fingerprint: true,
                    onlyIfSuccessful: false, followSymlinks: false
            }
        }
    }

}

