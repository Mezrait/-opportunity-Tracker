# Part A – Access Control in a Linux System

In this part I created a group and two users, checked how Linux stores them, and then tested how file and directory permissions decide what each user can do. At the end I tested the three special permission bits (SUID, SGID and the sticky bit).

## Environment and setup

I did this lab on Ubuntu 24.04.4 LTS running in WSL 2 on my Windows 11 laptop, not on the CSE-LABVM. All the commands are the same, but there are two practical differences:

- WSL has no graphical desktop, so I could not use "Logout → Switch User" like the lab sheet describes. Instead I switched users in the terminal with su - username, which starts a full login shell for that user. This is the command-line way of doing the same thing.
- The lab expects a VM that already has users like Alice, Bob, Eve and Eric. My system did not have them, but it had three accounts that already existed before this lab (fakeuser, fakeuser1 and malicious_actor, with home directories dated 23 September). So my user and group IDs are different from the ones in the lab sheet.

First I became root with sudo su. Since every screenshot must show my student ID, and in this lab it is also important to see which user is running each command, I changed the prompt to show the date, time, my ID and the current user and folder. I added the same line to /etc/skel/.bashrc before creating the new users, because every new user gets a copy of this file in their home directory, so sam and danny would also get the prompt automatically.

[IMG a35.png] Figure 1: Setting the prompt for root, for new users (/etc/skel) and for my own account

My first version used double quotes, and bash turned the \$ into a normal $ when it read the file. Because of this the root prompt ended with $ instead of #, which is misleading in a lab about privileges (# means root). I fixed it by replacing the line in all five .bashrc files with a single-quoted version. After the fix, root shows # and normal users show $.

[IMG c43_ps1.png] Figure 2: Fixing the prompt – after the fix the root prompt ends with #

## Part 1 – Adding a new group

I created the group with groupadd DEVELOPERS. Groups are stored in /etc/group, one per line, in the format name:password:GID:members. The x means the group password (if any) is kept in /etc/gshadow.

[IMG c43_group.png] Figure 3: The DEVELOPERS group at the end of /etc/group

DEVELOPERS got GID 1005 (in the lab sheet it was 1005 too, but only by chance, since the other groups on my system are different). This screenshot was taken after Part 2, so it already shows sam and danny as members.

## Part 2 – Adding users to the group

I created sam with adduser sam. adduser is the interactive Debian/Ubuntu tool: it creates the user and a private group with the same name, makes the home directory, copies the files from /etc/skel, asks for the password (samPass) and then asks for the GECOS information. For the full name I entered my own text instead of "Sam", so it appears in /etc/passwd later. At the end adduser also added sam to the extra group users.

[IMG a37.png] Figure 4: Creating the user sam with adduser

Then I added sam to DEVELOPERS with usermod -G DEVELOPERS sam and did the same steps for danny (password dannyPass).

[IMG a38.png] Figure 5: Adding sam to DEVELOPERS and creating danny

## Part 2 – Verifying users, groups and passwords

/etc/passwd stores one line per account: username:x:UID:GID:GECOS:home:shell. sam got UID 1006 and danny 1007, each with a private group of the same number, a home directory in /home and /bin/bash as the shell. The x in the second field means the password hash is not stored here. This is important because /etc/passwd must be readable by everyone (programs use it to convert UIDs to names), so keeping the hash in it would let any user copy it and try to crack it offline.

[IMG c39_passwd.png] Figure 6: The new users at the end of /etc/passwd

The hashes are kept in /etc/shadow, which only root can read.

[IMG a40.png] Figure 7: The entries for sam and danny in /etc/shadow

The fields are username:hash:last change:min:max:warn:… . Two things are different from the lab sheet:

- My hashes start with $y$, which means yescrypt, while the lab sheet shows $6$ (SHA-512 crypt). Ubuntu changed its default password hash to yescrypt in newer versions. Yescrypt is designed to need a lot of memory, which makes guessing passwords with GPUs much slower than with SHA-512 [1].
- The text between the second and third $ (j9T…) is the parameters and the random salt. Because of the salt, two users with the same password would still have different hashes.
- The number 20755 is the date of the last password change counted in days since 1 January 1970, which is 29 October 2026, the day I did the lab. 0:99999:7 means the password can be changed at any time, practically never expires, and the user is warned 7 days before expiry.

Finally I checked the group membership:

[IMG a41.png] Figure 8: Group membership of sam and danny

Both users are in DEVELOPERS. But I noticed that the group users is missing from the output of id, even though adduser added both users to it (Figure 4). The reason is that usermod -G sets the full list of supplementary groups, so it replaced users with DEVELOPERS. To add a group without removing the others, the correct command is usermod -aG DEVELOPERS sam (-a = append) [2]. In this lab nothing breaks, but on a real system this mistake could silently remove a user from an important group like sudo.

## Part 3 – Switching users and symbolic permissions

### Ubuntu 24.04 home directories are private by default

I switched to sam with su - sam, went to /home and listed the directories. Here my result was different from the lab sheet. In the lab every home directory is drwxr-xr-x (755), but on my system all of them, including my own, are drwxr-x--- (750). So when sam tried to enter danny's directory, he was already denied, before anyone changed any permission.

[IMG c42_sam.png] Figure 9: As sam – all home directories are 750 and sam cannot enter danny's folder

This happens because newer Ubuntu versions create home directories with mode 0750 (the HOME_MODE setting in /etc/login.defs) instead of 0755 [3]. In my opinion this is a good change. With 755, any user on the machine can browse other users' files by default, and most people never check this. With 750 the home directory is private unless the owner decides to share it, which follows the principle of least privilege.

### Recreating the lab's starting state

To be able to follow the rest of the lab, as root I set danny's home directory back to 755. Then sam could enter the directory (others have x), but touch new.txt was denied because others have no w.

[IMG a44.png] Figure 10: After chmod 755, sam can enter danny's folder but cannot create a file

For a directory the three permissions mean something different than for a file:

- r – list the names of the files inside (ls)
- w – create, delete or rename files inside
- x – enter the directory (cd) and access the files inside by name

### Getting root and removing execute for others

The lab gets root through a normal admin account and sudo, so I did the same: from sam I used su - hamerhadas (my own account, which asked for its password) and then sudo -i. In my case sudo -i did not ask for a password again.

[IMG a45.png] Figure 11: From sam to my admin account and then to root

As root I removed the execute permission for others with symbolic mode: chmod o-x danny. The directory changed from drwxr-xr-x to drwxr-xr--.

[IMG a46.png] Figure 12: chmod o-x on danny's home directory

Then I went back to sam (exit twice) and tried again. sam was denied, even though others still have r. Without x a user cannot enter the directory at all.

[IMG a47.png] Figure 13: sam cannot enter danny's folder after o-x

In symbolic mode the format is who (u, g, o, a), operator (+ adds, - removes, = sets exactly) and permissions (r, w, x). For example chmod g-w file removes write from the group and chmod a=r file makes the file read-only for everyone.

## Part 4 – Absolute (octal) permissions

In absolute mode each group of three permissions is written as one octal digit, where r = 4, w = 2 and x = 1, and the digit is the sum. For example 6 = 4 + 2 = rw- and 5 = 4 + 1 = r-x. Three digits give the permissions for user, group and others. The difference from symbolic mode is that octal sets all nine bits at once, while symbolic mode changes only the bits you name.

I switched to danny with su - danny (password dannyPass). As the owner, danny can change the permissions of his own directory without root. I used chmod 705 danny:

| Digit | Who | Binary | Permissions |
|---|---|---|---|
| 7 | user (danny) | 111 | rwx |
| 0 | group (danny) | 000 | --- |
| 5 | others | 101 | r-x |

[IMG a48.png] Figure 14: As danny – chmod 705 and creating test.txt

The directory changed from drwxr-xr-- to drwx---r-x. Then danny created test.txt. The new file got -rw-rw-r-- (664) without any chmod. This comes from the default umask 002 for normal users: new files start from 666 and the umask removes write from others.

Then I went back to sam:

[IMG a49.png] Figure 15: As sam – reading danny's folder works, creating a file is denied

sam could enter the directory and list test.txt (others have r-x), but touch sam.txt was denied (others have no w). One thing I found interesting: sam and danny are both in the DEVELOPERS group, but this does not help sam here. The group of danny's home directory is danny, not DEVELOPERS, so for this directory sam is in "others". Linux checks the categories in order (owner, then group, then others) and uses only the first one that matches.

## Part 5 – SUID, SGID and the sticky bit

For this self-learning part I made a test directory /srv/lab3 as root and ran the commands as sam and danny with su user -c "command", so I could stay in the root shell and still run each test as a normal user.

### SUID

I wrote a small C program that prints the real UID (who started the program) and the effective UID (whose permissions the program uses). I compiled it with gcc and made danny the owner.

[IMG a50.png] Figure 16: The C program, compiling it, and making danny the owner

Then sam ran the program before and after setting SUID:

[IMG a56.png] Figure 17: Without SUID the program runs as sam, with SUID it runs as danny

- Without SUID (-rwxr-xr-x): real UID 1006 (sam) and effective UID 1006 (sam). The program runs with the rights of the user who started it, which is the normal case.
- After chmod u+s (-rwsr-xr-x, the x of the owner becomes s): real UID still 1006 (sam), but effective UID 1007 (danny). So sam is running code with danny's permissions.

A real example is /usr/bin/passwd, which is SUID root:

[IMG c54_passwd.png] Figure 18: passwd has the SUID bit and is owned by root

A normal user must be able to change their own password, but the hash is in /etc/shadow, which only root can write. SUID lets passwd run as root for this one job. In my opinion SUID is the most dangerous of the three bits: if a SUID-root program has a bug or lets the user run other commands, any user can become root. That is why administrators should keep the number of SUID files small and check them regularly, for example with find / -perm -4000.

### SGID on a directory

I created a shared directory with group DEVELOPERS and mode 775. sam created before.txt, then I set SGID with chmod g+s and sam created after.txt.

[IMG a51.png] Figure 19: SGID test – group of files created before and after g+s

[IMG a55.png] Figure 20: The shared directory with the SGID bit (drwxrwsr-x)

before.txt got the group sam (sam's primary group, the normal behaviour), but after.txt got the group DEVELOPERS, the group of the directory. So with SGID all new files in a shared folder belong to the team's group automatically, and the other members can work with them without someone having to run chgrp each time.

### Sticky bit

I created /tmp/teststicky with mode 777 (everyone can write) and tested if danny can delete a file that belongs to sam, first without and then with the sticky bit.

[IMG a53.png] Figure 21: Sticky bit test

- Without the sticky bit (drwxrwxrwx): danny deleted sam1.txt without any problem, even though the file belongs to sam. This is because deleting a file is controlled by the w permission on the directory, not by the permissions of the file.
- With chmod +t (drwxrwxrwt, the x of others becomes t): danny got "Operation not permitted" on sam2.txt, but sam could delete his own file. With the sticky bit only the owner of the file, the owner of the directory or root can delete or rename it.

The last command shows that /tmp itself has the sticky bit. That is why all users can share /tmp without being able to delete each other's files.

In my first attempt at this test I used rm without -f. Because the files are not writable by danny, rm asked "remove write-protected regular empty file?" and pressing Enter answered no, so nothing was really tested. I repeated the test with rm -f, which does not ask.

## Part A summary

| Bit | Set with | Shown as | Effect |
|---|---|---|---|
| SUID | chmod u+s (4xxx) | s in the user x position | program runs with the file owner's UID |
| SGID | chmod g+s (2xxx) | s in the group x position | new files inherit the directory's group |
| Sticky | chmod +t (1xxx) | t in the others x position | only the owner can delete files in the directory |

Part A showed me that Linux access control is simple (owner, group, others and r, w, x) but the details matter: x on a directory decides if you can enter it, w on a directory decides if you can delete files in it, and usermod -G can quietly remove groups. I also saw that the defaults change between versions. Ubuntu 24.04 is stricter than the system the lab was written for (private home directories, yescrypt hashes), so it is important to check the real system and not assume.
