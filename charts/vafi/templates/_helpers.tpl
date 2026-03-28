{{/*
Expand the name of the chart.
*/}}
{{- define "vafi.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "vafi.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Common labels applied to every resource.
*/}}
{{- define "vafi.labels" -}}
helm.sh/chart: {{ include "vafi.name" . }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/part-of: vafi
{{- end }}

{{/*
Selector labels for a given component.
IMPORTANT: Does NOT include version — selectors must be immutable.
Usage: {{ include "vafi.selectorLabels" (dict "root" . "component" "executor") }}
*/}}
{{- define "vafi.selectorLabels" -}}
app.kubernetes.io/name: {{ include "vafi.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/*
Secret name used by all components.
Uses existingSecret if set, otherwise generates from release name.
*/}}
{{- define "vafi.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else -}}
{{ include "vafi.fullname" . }}-secrets
{{- end -}}
{{- end }}

{{/*
CXDB service name.
*/}}
{{- define "vafi.cxdbName" -}}
{{ include "vafi.fullname" . }}-cxdb
{{- end }}

{{/*
Common environment variables for the executor container.
*/}}
{{- define "vafi.executorEnv" -}}
- name: VF_AGENT_ID
  value: {{ .Values.executor.agentId | quote }}
- name: VF_AGENT_ROLE
  value: {{ .Values.executor.role | quote }}
- name: VF_AGENT_TAGS
  value: {{ .Values.executor.tags | quote }}
- name: VF_VTF_API_URL
  value: {{ .Values.vtf.apiUrl | quote }}
- name: VF_VTF_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ include "vafi.secretName" . }}
      key: vtf-token
- name: VF_POLL_INTERVAL
  value: {{ .Values.executor.pollInterval | quote }}
- name: VF_TASK_TIMEOUT
  value: {{ .Values.executor.taskTimeout | quote }}
- name: VF_MAX_REWORK
  value: {{ .Values.executor.maxRework | quote }}
- name: VF_MAX_TURNS
  value: {{ .Values.executor.maxTurns | quote }}
- name: VF_HEARTBEAT_INTERVAL
  value: {{ .Values.executor.heartbeatInterval | quote }}
- name: VF_SESSIONS_DIR
  value: {{ .Values.executor.sessionsDir | quote }}
{{- if .Values.cxdb.enabled }}
- name: VF_CXDB_URL
  value: "http://{{ include "vafi.cxdbName" . }}:80"
{{- if .Values.cxdb.publicUrl }}
- name: VF_CXDB_PUBLIC_URL
  value: {{ .Values.cxdb.publicUrl | quote }}
{{- end }}
{{- end }}
- name: ANTHROPIC_AUTH_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ include "vafi.secretName" . }}
      key: anthropic-auth-token
- name: ANTHROPIC_BASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "vafi.secretName" . }}
      key: anthropic-base-url
{{- end }}

{{/*
Environment variables for the judge container.
Same structure as executor but reads from .Values.judge.
*/}}
{{- define "vafi.judgeEnv" -}}
- name: VF_AGENT_ID
  value: {{ .Values.judge.agentId | quote }}
- name: VF_AGENT_ROLE
  value: {{ .Values.judge.role | quote }}
- name: VF_AGENT_TAGS
  value: {{ .Values.judge.tags | quote }}
- name: VF_VTF_API_URL
  value: {{ .Values.vtf.apiUrl | quote }}
- name: VF_VTF_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ include "vafi.secretName" . }}
      key: vtf-token
- name: VF_POLL_INTERVAL
  value: {{ .Values.judge.pollInterval | quote }}
- name: VF_TASK_TIMEOUT
  value: {{ .Values.judge.taskTimeout | quote }}
- name: VF_MAX_TURNS
  value: {{ .Values.judge.maxTurns | quote }}
- name: VF_HEARTBEAT_INTERVAL
  value: {{ .Values.judge.heartbeatInterval | quote }}
- name: VF_SESSIONS_DIR
  value: {{ .Values.judge.sessionsDir | quote }}
{{- if .Values.cxdb.enabled }}
- name: VF_CXDB_URL
  value: "http://{{ include "vafi.cxdbName" . }}:80"
{{- if .Values.cxdb.publicUrl }}
- name: VF_CXDB_PUBLIC_URL
  value: {{ .Values.cxdb.publicUrl | quote }}
{{- end }}
{{- end }}
- name: ANTHROPIC_AUTH_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ include "vafi.secretName" . }}
      key: anthropic-auth-token
- name: ANTHROPIC_BASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "vafi.secretName" . }}
      key: anthropic-base-url
{{- end }}
