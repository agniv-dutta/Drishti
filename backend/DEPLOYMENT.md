# Deployment

## Development

From `backend/`:

```powershell
docker compose up --build
```

The API is available at `http://localhost:8000`; PostgreSQL and Redis are reachable only by services on the Compose internal network. Put local values in `.env.dev`.

## Production target

Deploy the image to ECS Fargate or EKS behind an internet-facing Application Load Balancer:

- Terminate HTTPS at the ALB with an ACM certificate; redirect HTTP to HTTPS.
- Run at least two API tasks across availability zones. Use `/health` for the target-group health check.
- Store PostgreSQL in Amazon RDS for PostgreSQL 15 with Multi-AZ, automated backups, encryption, and credentials in Secrets Manager.
- Use ElastiCache for Redis with replication, automatic failover, encryption in transit, and AUTH enabled.
- Keep RDS and Redis in private subnets. Allow inbound access only from the API security group.
- Configure service autoscaling at CPU `70%` and memory `80%`; set minimum capacity to two tasks.
- Send container stdout/stderr to CloudWatch Logs with retention and KMS encryption.
- Enable AWS X-Ray tracing through the X-Ray daemon sidecar/daemonset and task IAM permissions.
- Inject production settings and Razorpay live credentials from Secrets Manager, with `RAZORPAY_ENVIRONMENT=production`.

Infrastructure should be managed with Terraform or CloudFormation. The minimum resources are a VPC with public/private subnets, ALB/listener/target group, ECS service or EKS deployment, RDS instance, ElastiCache replication group, CloudWatch log group, IAM roles, security groups, autoscaling policies, ACM certificate, and X-Ray permissions.

Do not use the development Compose credentials, database, or Redis volumes in production.
