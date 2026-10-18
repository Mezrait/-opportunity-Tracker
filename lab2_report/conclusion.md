# Conclusion

This lab showed me several important points about secret-key encryption:

- A monoalphabetic substitution cipher has a huge key space (26!), but it is still easy to break because it keeps the letter frequencies of the language. In Task 2 I recovered the whole article with only the frequency table and some guessing about common words.
- Modern ciphers like AES are strong, but the way they are used (the mode) matters just as much. In Task 4 the same AES key in ECB mode still showed the shapes of the picture, while CBC mode hid them completely.
- Older ciphers like Blowfish are now disabled by default in OpenSSL 3, which shows how recommendations change over time.
- Different modes react differently to errors. OFB only loses one bit, ECB loses one block, CBC and CFB lose one block plus one bit. Because a bit flip can pass through to the plaintext without being noticed, encryption alone does not give integrity, and a MAC or an authenticated mode such as AES-GCM is needed in practice.

Some problems I had during the lab were that the bless hex editor is not available on Ubuntu 24.04 and that my edits in GHex were not saved, so I used a short Python command to flip the bit. I also found that the tr command given in Task 1 does not remove square brackets. Solving these problems helped me understand the commands better than just running them.
