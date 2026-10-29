# Introduction

This lab is about authentication and access control. In Part A I worked with local Linux accounts: creating users and groups, looking at how passwords are stored, and controlling access to directories and files with normal permissions and the special bits SUID, SGID and the sticky bit. In Part B I used Keycloak, an open-source identity provider, to manage users, enable two-factor authentication and issue access tokens for applications.

## Lab environment

- Windows 11 laptop with Ubuntu 24.04.4 LTS running in WSL 2 (instead of the CSE-LABVM)
- Docker Desktop with WSL integration, used to run Keycloak in Part B
- A terminal prompt that shows the date, time, my student ID (1093911) and the current user in every screenshot
