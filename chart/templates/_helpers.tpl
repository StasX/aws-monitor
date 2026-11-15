{{/* Shared resource labels. */}}
{{- define "exam.labels" -}}
generator: helm
name: {{ .Release.Name }}
{{- end }}

