# This Dockerfile creates a minimal container image
# containing a single wheel file for distribution via a container registry.

# The path to the wheel file to be included is passed as a build argument.
ARG WHEEL_PATH
# Use a minimal 'scratch' image
FROM scratch
# Copy the wheel file from the build context to the root of the image
COPY ${WHEEL_PATH} /
