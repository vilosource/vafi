ARG REGISTRY=vafi
FROM ${REGISTRY}/vafi-base:latest

## Harness boundary scripts
COPY init.sh connect.sh run.sh /opt/vf-harness/
RUN chmod +x /opt/vf-harness/init.sh /opt/vf-harness/connect.sh /opt/vf-harness/run.sh

USER agent
