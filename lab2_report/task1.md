# Task 1 – Encryption using Substitution Cipher

In this task I encrypted my own short English article with a monoalphabetic substitution cipher. In this kind of cipher every plaintext letter is always replaced by the same ciphertext letter, so the key is just a permutation of the 26 letters of the alphabet.

## Step 1 – Generating the encryption key

I created a small Python script called keygen.py. It uses random.sample() to shuffle the string "abcdefghijklmnopqrstuvwxyz" and prints the shuffled alphabet, which is used as the substitution table (key).

[IMG 1.png] Figure 1: keygen.py and the generated key

The key generated was:

    Plain:  abcdefghijklmnopqrstuvwxyz
    Key:    atqkdmpwghblzxvcfnueisjyro

This means a→a, b→t, c→q, d→k, e→d and so on. I checked that the key contains all 26 letters with no repetition, otherwise two plaintext letters would map to the same ciphertext letter and decryption would not be possible. One thing I noticed is that the letter "a" maps to itself. This is allowed in a random permutation, and it shows that a random key can leave some letters unchanged, which gives a small hint to an attacker.

## Step 2 – Preparing the article

I took a paragraph about symmetric and asymmetric cryptosystems from the Wikipedia article "Cryptography" [1] and saved it in article.txt.

[IMG 3.png] Figure 2: The original article saved in article.txt

Then I simplified the text with two tr commands:

    tr '[:upper:]' '[:lower:]' < article.txt > lowercase.txt
    tr -cd '[a-z][\n][:space:]' < lowercase.txt > plaintext.txt

The first command converts all capital letters to small letters. The second command uses -c (complement) and -d (delete) so it deletes every character that is NOT a lowercase letter, a newline or a space. So all punctuation and numbers are removed but the spaces stay, which keeps the word boundaries.

[IMG 5.png] Figure 3: Preprocessing commands and plaintext.txt

## Step 3 – Encryption with tr

To encrypt I used tr again, mapping the normal alphabet to my key:

    tr 'abcdefghijklmnopqrstuvwxyz' 'atqkdmpwghblzxvcfnueisjyro' < plaintext.txt > my_ciphertext.txt

Only letters are changed, spaces and newlines stay the same. I saved the output as my_ciphertext.txt so I would not overwrite the ciphertext.txt that is given for Task 2.

[IMG 4a.png] Figure 4: The ciphertext I created (my_ciphertext.txt)

For example the first words "there are two main types" became "ewdnd and ejv zagx ercdu". In "there" → "ewdnd" the letter e appears twice and both times it became d, so repeated letters in the plaintext stay repeated in the ciphertext at the same positions. This is exactly the weakness that frequency analysis uses in Task 2.

## Verification – Decryption

To make sure the encryption was correct I decrypted the file by swapping the two sets in tr (key → alphabet) and compared the result with plaintext.txt using diff. diff printed nothing and the echo printed MATCH, so the decrypted file is identical to the plaintext.

[IMG 4b.png] Figure 5: Decryption and verification with diff

## Observations

- The numbers like "1970s" and "20th" lost their digits, so "1970s" became just "s" and "20th" became "th". This is expected because the command deletes digits.
- The citation brackets "[14]" and "[15]" became "[]" instead of being removed completely. The reason is that inside the tr set '[a-z][\n][:space:]' the square brackets are treated as normal characters and not as part of a range, so "[" and "]" are also kept. A cleaner command would be tr -cd 'a-z\n[:space:]'. It does not affect the encryption since tr only changes letters, but the brackets give a small extra hint to an attacker.
- Since spaces are kept, the attacker can see the word lengths. For example one-letter words can only be "a" or "i", and three-letter words are often "the" or "and". In real use of a monoalphabetic cipher the spaces would be removed.

## References

[1] Wikipedia, "Cryptography," Wikipedia, The Free Encyclopedia. [Online]. Available: https://en.wikipedia.org/wiki/Cryptography. [Accessed: Oct. 18, 2026].
