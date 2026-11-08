# RAHBAR chat UI: static files served by an unprivileged nginx on 8080.
# Build context: ui/   ->   docker build -t rahbar-ui:dev ui
# No build step (plain HTML + JS), so a single stage is enough: there is no Node
# toolchain to leave behind.
FROM nginxinc/nginx-unprivileged:alpine

# patch OS packages the base image has not picked up yet (Trivy gate)
USER root
RUN apk upgrade --no-cache

COPY nginx.conf /etc/nginx/nginx.conf
COPY index.html /usr/share/nginx/html/index.html

# the base image already runs as uid 101; stated explicitly so it is visible here
USER 101
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
