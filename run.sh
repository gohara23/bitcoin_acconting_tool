docker build -t btc-accounting-tool .
docker run -v $(pwd)/data:/app/data btc-accounting-tool
