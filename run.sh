docker build -t btc-accounting-tool .
docker run --rm -v $(pwd)/data:/app/data btc-accounting-tool
