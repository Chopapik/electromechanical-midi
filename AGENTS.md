# Local application deployment

After implementing changes to the web application, backend, configuration, or
firmware bundled in the application, rebuild and restart the `orchestra`
container with `docker compose up -d --build orchestra` so the user can see the
changes immediately. Verify that the container is healthy and the running
application serves the new version before reporting completion.
