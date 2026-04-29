# Listmonk Docker Setup

This page is for running a local Listmonk instance with Docker. To run the MCP server itself as a container, see [Container Image](container.md).

## Quick Docker Setup

1. **Use the provided Docker Compose file:**
   ```bash
   # Copy the compose file to your desired location
   cp docs/listmonk-docker-compose.yml docker-compose.yml
   ```

2. **Start Listmonk:**
   ```bash
   docker-compose up -d
   ```

3. **Access Listmonk:**
   - Open http://localhost:9000
   - Follow the setup wizard
   - Create an admin user
   - Go to Settings → Users to create API credentials

## Docker Compose Configuration

The provided configuration includes:

- **Listmonk**: Newsletter management application
- **PostgreSQL**: Database backend
- **Persistent volumes**: For data retention
- **Environment variables**: Pre-configured for development

## API Setup

After Listmonk is running:

1. Access the admin panel at http://localhost:9000
2. Go to Settings → Users
3. Create a new API user with appropriate permissions
4. Generate an API token
5. Use these credentials in your MCP configuration

## Production Considerations

For production deployment:

- Change default passwords
- Use proper SSL certificates  
- Configure proper backup strategies
- Review security settings
- Use environment-specific configuration files
