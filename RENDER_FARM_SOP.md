# RenderFarm Professional - User Operating Guide

## Table of Contents
1. [Getting Started](#getting-started)
2. [Web Interface Access](#web-interface-access)
3. [Job Submission](#job-submission)
4. [Monitoring Jobs](#monitoring-jobs)
5. [Basic Troubleshooting](#basic-troubleshooting)
6. [Best Practices](#best-practices)

---

## Getting Started

RenderFarm Professional is a distributed rendering system for Nuke and Silhouette projects.

### System Access
- Contact your IT administrator for system access
- Ensure you have proper network connectivity
- Verify you have access to shared project storage

### Supported File Types
- **Nuke**: .nk, .nuke files
- **Silhouette**: .sfx files

---

## Web Interface Access

### Accessing the System
1. Open your web browser
2. Navigate to the render farm web interface (obtain URL from IT administrator)
3. The dashboard will load automatically

### Dashboard Overview
The main interface consists of several tabs:
- **Overview**: System status and active jobs
- **Jobs**: Submit new jobs and monitor existing ones  
- **Workers**: View connected render nodes

---

## Job Submission

### Basic Job Submission Process

#### Step 1: Navigate to Jobs Tab
1. Click on the "Jobs" tab in the main interface
2. Click "Submit New Job" button

#### Step 2: Select Project File
1. Click "Browse" to navigate to your project location
2. Select your .nk (Nuke) or .sfx (Silhouette) file
3. Ensure the file is accessible on the shared network

#### Step 3: Configure Basic Settings
- **Renderer**: Choose Nuke or Silhouette
- **Version**: Select the appropriate software version
- **Frame Range**: Enter frames to render (e.g., 1-100, or 10-20)
- **Output Path**: Specify where rendered files should be saved
- **Priority**: Choose job priority level

#### Step 4: Submit Job
1. Review your settings
2. Click "Submit Job"
3. Your job will appear in the jobs list

---

## Monitoring Jobs

### Job Status Overview
Your submitted jobs can have the following statuses:
- **Pending**: Waiting to start rendering
- **Running**: Currently being rendered
- **Completed**: Successfully finished
- **Failed**: Encountered errors
- **Paused**: Temporarily stopped

### Managing Your Jobs

#### Viewing Job Progress
1. Go to the Jobs tab
2. Find your job in the list
3. View progress percentage and status
4. Check estimated completion time

#### Controlling Jobs
- **Pause**: Click the pause button to temporarily stop a job
- **Resume**: Restart a paused job
- **Cancel**: Stop a job permanently
- **View Logs**: Click on a job to see detailed information

#### Understanding Job Details
- **Frame Progress**: Shows which frames have completed
- **Render Times**: Average time per frame
- **Worker Assignment**: Which computers are working on your job

---

## Basic Troubleshooting

### Common Issues and Solutions

#### Cannot Access Web Interface
**What you see**: Browser shows "page cannot be displayed" or connection errors

**What to try**:
1. Check that you have the correct web address
2. Try refreshing the page
3. Contact IT support if the problem persists

#### Job Stuck in "Pending" Status  
**What you see**: Job shows as "Pending" for a long time without starting

**What to try**:
1. Check if there are available worker computers (Workers tab)
2. Verify your project file path is correct and accessible
3. Try resubmitting the job with a smaller frame range
4. Contact support if workers are offline

#### Job Failed to Complete
**What you see**: Job status shows "Failed" with error messages

**What to try**:
1. Click on the job to view error details
2. Check if the project file still exists at the specified location
3. Verify output path has enough disk space
4. Try rendering a single frame first to test
5. Contact support with error messages

#### Slow Rendering Performance
**What you see**: Jobs taking much longer than expected

**What to try**:
1. Check system status on Overview tab for resource usage
2. Try reducing batch size (render fewer frames at once)
3. Verify network connection is stable
4. Schedule large jobs during off-peak hours

### Getting Help
- **First**: Check this guide for common solutions
- **Second**: Look at job logs for specific error messages  
- **Third**: Contact your IT administrator with details about the problem

---

## Best Practices

### Job Submission Guidelines

#### File Management
- Always use network paths that all computers can access
- Keep project files organized in shared locations  
- Ensure adequate disk space in output directories
- Use descriptive job names for easy identification

#### Optimal Settings
- **Frame Range**: Start with small tests (1-10 frames) before full jobs
- **Batch Size**: Use 1-5 frames per batch for most projects
- **Priority**: Use "High" priority sparingly for urgent work
- **Output Format**: Confirm output format matches your needs

#### Resource Management  
- Schedule large jobs during off-peak hours when possible
- Monitor job progress and cancel jobs that are no longer needed
- Clean up old completed jobs to keep the interface organized

### Working Efficiently

#### Before Submitting Jobs
- [ ] Test render locally to verify project works correctly
- [ ] Check that all assets and textures are accessible via network
- [ ] Verify output directory exists and has sufficient space
- [ ] Choose appropriate frame range and batch settings

#### While Jobs are Running
- [ ] Monitor progress periodically via the web interface
- [ ] Check for any error messages in job details
- [ ] Be prepared to pause jobs if priority work comes in
- [ ] Keep an eye on overall system resources

#### After Jobs Complete
- [ ] Verify output files are created successfully
- [ ] Check render quality for any issues
- [ ] Clean up any temporary files if needed
- [ ] Archive or move final renders to appropriate storage

### Team Coordination
- Communicate with team members about large rendering jobs
- Use priority settings appropriately to respect shared resources
- Keep project files organized and accessible to all users
- Follow naming conventions for projects and output files

---

## Contact Information

For technical support or questions about using the render farm system:

**Primary Contact**: Your IT Administrator  
**Email**: [Contact IT for current email]  
**Phone**: [Contact IT for current phone]

**For urgent rendering deadlines or system outages, contact support immediately.**

---

*This guide covers the basic operation of the RenderFarm Professional system. For advanced features or system administration, contact your IT support team.*