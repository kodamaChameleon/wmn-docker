<img src="./wmn-docker.png" height=400>  

![Python](https://img.shields.io/badge/Python-3.10.12-yellow.svg?logo=python) <!-- GEN:Django -->![Docker](https://img.shields.io/badge/Docker-24.0.7-blue.svg?logo=docker)<!-- GEN:stop -->

Version: 0.0.1_beta  

> 🚧 Pardon our mess! In case *beta* is not obvious, WMN-Docker is an active construction zone. We make no guarantees about stability while we are in development.

## 💎 About

WhatsMyName (WMN) by [Micah "WebBreacher" Hoffman](https://webbreacher.com/) was created in 2015 with the goal of discovering usernames on a given website. WMN-Docker creates an API wrapper in a containerized Docker environment around WMN for integration, modularity, and scalability with other OSINT tooling.

## ✨ Features

WMN-Docker offers straightforward functionality to compliment the original intent of WMN while ensuring a basic level of security and bonus features.

- **JWT Authentication**
  - Optional, enabled by default
  - `/api/v1/token`
- **Username Lookup**
  - Initiate a username lookup across the web
  - `/api/v1/lookup`
- **Job Results**
  - Returns the results of username lookup
  - Results are cached for performance (default 1 hour)
  - `/api/v1/status/{job_id}`

## 🛠️ Getting Started

### Prerequisites

- Docker
- Docker-Compose
- Python 3.10

### Installation
- Clone the repository using `git clone https://github.com/kodamaChameleon/wmn-docker.git`
- Environment
  - **Quick Setup**: Initialize the local .env and pull container images from DockerHub using `python3 client.py --setup`
  - **Contributing**: Initialize the local .env and build container from source code with `python3 client.py --setup dev`

### Initialize User Database
By default, authentication is required. To initialize the user database and retrieve credentials:
- Execute `docker ps` to obtain the container id of the api.
- Launch a bash shell with `docker exec -it <api_container_id> bash`
- Initialize the database by running `python3 users.py initialize`
- Save the initial credentials in a safe location.

> 💡 Additional user management features are available from the users.py command line utility inside the container. Just run `python3 users.py -h`

## 🤝Contributing
Contributions are welcome! Please read the [CONTRIBUTING.md](CONTRIBUTING.md) for details on how to get involved.

## 📜 License

![Creative Commons](https://img.shields.io/badge/Creative_Commons-4.0-white.svg?logo=creativecommons)

[Creative Commons Attribution-ShareAlike 4.0 International License](http://creativecommons.org/licenses/by-sa/4.0/).
