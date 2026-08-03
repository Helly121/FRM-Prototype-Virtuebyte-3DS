# AWS Deployment Guide (Step-by-Step)

This guide is designed for absolute beginners. It walks you through deploying the 3DS Anomaly Detection MVP to AWS using an **Amazon RDS** database and an **Amazon EC2** virtual server.

## Step 1: Provision the PostgreSQL Database (Amazon RDS)
We need a managed database to hold our `card_profiles` and transaction history.
1. Log into the AWS Console and search for **RDS**.
2. Click **Create database**.
3. Select **PostgreSQL** (Version 16).
4. Choose the **Free tier** or **Dev/Test** template.
5. Under **Settings**:
   - Set the DB instance identifier to `anomaly-db`.
   - Set the Master username to `postgres`.
   - Set a strong Master password and save it somewhere secure.
6. Under **Connectivity**:
   - Set **Public access** to `No` (for security).
   - Create a new VPC security group named `anomaly-db-sg`.
7. Click **Create database**. This will take ~5-10 minutes. 
8. Once created, click on the database and copy the **Endpoint** (it looks like `anomaly-db.xxx.region.rds.amazonaws.com`). This is your database URL.

## Step 2: Initialize the Database
Before starting the API, the database needs the schema and ML model data.
1. Since the DB is not public, you must run a temporary EC2 instance (or use AWS CloudShell inside the VPC).
2. Connect to the DB using the endpoint:
   `psql -h <ENDPOINT> -U postgres -d postgres`
3. Copy/paste the contents of `postgres/init.sql` to build the tables.

## Step 3: Provision the Application Server (Amazon EC2)
1. In the AWS Console, search for **EC2**.
2. Click **Launch instance**.
3. Name it `anomaly-engine-server`.
4. Select **Ubuntu 24.04 LTS** as the AMI (Amazon Machine Image).
5. Choose an Instance type (e.g., `t3.medium` is recommended for ML workloads).
6. Create a new **Key pair (RSA, .pem)**. Download this file! You need it to connect to the server.
7. Under **Network settings**, check:
   - Allow SSH traffic from (My IP)
   - Allow HTTP traffic from the internet (This opens Port 80 for the API Gateway)
8. Click **Launch instance**.

## Step 4: Configure the EC2 Server
1. Wait for the instance to show "Running". Copy its **Public IPv4 address**.
2. Open your local terminal and connect to the server using the `.pem` key you downloaded:
   ```bash
   ssh -i "your-key.pem" ubuntu@<PUBLIC_IP>
   ```
3. Install Docker and configure Swap Space (Crucial for ML on Free Tier!):
   ```bash
   sudo apt update
   sudo apt install docker.io docker-compose -y
   sudo usermod -aG docker ubuntu
   
   # Allocate 2GB of Swap space so the ML model doesn't run out of memory
   sudo fallocate -l 2G /swapfile
   sudo chmod 600 /swapfile
   sudo mkswap /swapfile
   sudo swapon /swapfile
   echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

   # Exit and reconnect to apply Docker permissions
   exit
   ssh -i "your-key.pem" ubuntu@<PUBLIC_IP>
   ```

## Step 5: Deploy the Code
1. Upload your code to a private GitHub repository, or use `scp` to copy the files directly from your computer to the EC2 server.
   *(Assuming you uploaded to GitHub, clone it on the EC2 server)*:
   ```bash
   git clone https://github.com/your-username/frm-anomaly-mvp.git
   cd frm-anomaly-mvp
   ```
2. **Crucial**: Make sure you have trained the model locally first, and that `model/isolation_forest.pkl` exists in your code directory, because the Dockerfile now bakes it into the image!
3. Set your environment variables on the EC2 server:
   ```bash
   export PG_DSN="postgresql://postgres:<PASSWORD>@<RDS_ENDPOINT>:5432/postgres"
   export API_KEY="your-secret-production-key"
   ```
4. Start the production containers:
   ```bash
   docker-compose -f docker-compose.prod.yml up -d --build
   ```

## Step 6: Test the Deployment
1. Wait a few seconds for the containers to spin up.
2. Open your web browser and navigate to the EC2 server's Public IP address:
   `http://<PUBLIC_IP>`
3. You should see the Presentation Dashboard!
4. Try submitting a transaction in the simulator. The Node.js gateway (Port 80) will proxy it to the internal FastAPI engine, which will query the Amazon RDS database, run the ML model, and return the result.
