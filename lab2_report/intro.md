# Introduction

The aim of this lab is to get hands-on experience with secret-key (symmetric) encryption and some of its weaknesses. In the first two tasks I worked with the monoalphabetic substitution cipher: first I encrypted my own article, and then I broke a given ciphertext using frequency analysis. In the last three tasks I used OpenSSL to encrypt files with modern block ciphers (AES and Blowfish), compared the ECB and CBC modes by encrypting a picture, and studied how a single corrupted bit affects the decrypted data in the ECB, CBC, CFB and OFB modes.

## Lab setup

All the tasks were done on Ubuntu 24.04 (running in WSL on Windows 11) with OpenSSL 3.0.13. I downloaded and unzipped the Files folder from Blackboard, which contains freq.py, ciphertext.txt and pic_original.bmp. Before starting, I changed the terminal prompt so that the date, the time and my student ID appear in every screenshot:

    PS1="\d \@ [1093911]"

The same key (00112233445566778899aabbccddeeff) and IV (0102030405060708090a0b0c0d0e0f10) were used in Tasks 3, 4 and 5 so the results can be repeated.
