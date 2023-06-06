# Start with the Python Alpine image as the build image
FROM python:3.11-alpine

# Update packages if necessary
RUN apk update

# Add the required packages, disabling cache to reduce the size of the image
COPY ./requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt

# Set the entrypoint to run uvicorn on port 8020
CMD [ "uvicorn", "src.index:app", "--host", "0.0.0.0", "--port", "8020" ]
