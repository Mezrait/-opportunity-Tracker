# Task 3 – Encryption using Different Ciphers and Modes

In this task I used the openssl enc command to encrypt and decrypt a file with three different ciphers: AES-128 in CBC mode, AES-128 in CFB mode and Blowfish in CBC mode [1]. The general form of the command is:

    openssl enc -ciphertype -e -in plain.txt -out cipher.bin -K <key in hex> -iv <iv in hex>

The options I used are:

- -e / -d: encrypt or decrypt
- -in / -out: input and output file
- -K: the key given directly in hexadecimal
- -iv: the initialisation vector in hexadecimal

Because I give the key and IV directly with -K and -iv, openssl does not use a password or a salt, so I can decrypt with exactly the same values later.

## Setup

I created a folder task3 and a small plaintext file plain.txt containing one sentence. The file is 63 bytes long (62 characters + the newline added by echo).

[IMG 13.png] Figure 13: Creating the plaintext file

For all three ciphers I used the same 128-bit key 00112233445566778899aabbccddeeff. For AES the IV is 16 bytes (0102030405060708090a0b0c0d0e0f10) because the AES block size is 128 bits. For Blowfish the IV is only 8 bytes (0102030405060708) because Blowfish has a 64-bit block size.

## Cipher 1 – AES-128-CBC

AES (Advanced Encryption Standard) is a block cipher with a 128-bit block and here a 128-bit key. In CBC (Cipher Block Chaining) mode each plaintext block is XORed with the previous ciphertext block before it is encrypted, and the first block is XORed with the IV. Because of this, the same plaintext block gives a different ciphertext block depending on what came before it.

[IMG 14.png] Figure 14: AES-128-CBC encryption, ciphertext in hex (xxd) and decryption

The xxd output shows that the ciphertext is random-looking bytes with no readable text. The decrypted file dec_aes_cbc.txt is exactly the same as the original sentence. The ciphertext is 64 bytes (4 lines of 16 bytes in xxd), which is 1 byte more than the plaintext. The reason is that CBC can only encrypt full blocks, so openssl adds PKCS#7 padding to fill the last block: 63 bytes → 4 × 16 = 64 bytes. The padding is removed automatically when decrypting.

## Cipher 2 – AES-128-CFB

This uses the same AES algorithm but in CFB (Cipher Feedback) mode. In CFB the block cipher is used to produce a key stream: the IV (and after that the previous ciphertext block) is encrypted and the result is XORed with the plaintext. So AES works like a stream cipher here, and only the encryption function of AES is used for both encryption and decryption.

[IMG 15.png] Figure 15: AES-128-CFB encryption, ciphertext in hex (xxd) and decryption

Even though the key, IV and plaintext are the same as in Cipher 1, the ciphertext is completely different, because the mode is different. Decryption gives back the original sentence. The important difference is the size: the last xxd line has only 15 bytes, so the ciphertext is 63 bytes, exactly the same as the plaintext. CFB does not need padding because the plaintext is just XORed with the key stream, so the last block can be cut to any length.

## Cipher 3 – Blowfish-CBC

Blowfish is an older block cipher designed by Bruce Schneier in 1993. It has a 64-bit block and a variable key length (32 to 448 bits).

When I first ran the command, it failed with the error "Error setting cipher BF-CBC … unsupported".

[IMG 16.png] Figure 16: Blowfish error in OpenSSL 3

The reason is that my system uses OpenSSL 3.0.13. In OpenSSL 3, older or weaker algorithms such as Blowfish, DES, RC4 and CAST were moved to the "legacy provider", which is not loaded by default [2]. To use it, I added -provider legacy -provider default to the command (the default provider is still needed for the other functions).

[IMG 17.png] Figure 17: Blowfish-CBC encryption with the legacy provider, ciphertext and decryption

With the legacy provider, encryption and decryption worked and the decrypted file matches the original. The ciphertext is also 64 bytes: 63 bytes padded up to 8 × 8 = 64 bytes, because the Blowfish block is 8 bytes.

## Comparing the file sizes

[IMG 18.png] Figure 18: OpenSSL version and file sizes

| File | Size (bytes) | Reason |
|---|---|---|
| plain.txt | 63 | original text |
| cipher_aes_cbc.bin | 64 | padded to a multiple of 16 (AES block) |
| cipher_aes_cfb.bin | 63 | CFB is a stream mode, no padding |
| cipher_bf_cbc.bin | 64 | padded to a multiple of 8 (Blowfish block) |

Here both CBC files happen to be 64 bytes, but for a different reason. For example, if the plaintext was 65 bytes, AES-CBC would give 80 bytes (5 blocks of 16) and Blowfish-CBC would give 72 bytes (9 blocks of 8), while CFB would stay 65 bytes.

## Observations

- The same plaintext and key give totally different ciphertexts with different algorithms and modes, so to decrypt we need to know the algorithm, the mode, the key and the IV.
- Block modes like CBC need padding, so the ciphertext can be bigger than the plaintext. Stream-like modes like CFB keep the same size.
- The fact that OpenSSL 3 disables Blowfish by default shows that it is not recommended anymore. Its 64-bit block is small: after encrypting a lot of data with the same key (around 32 GB) blocks start to repeat, which is the idea behind the Sweet32 attack [3]. For new systems AES is the better choice.
- In this lab I used a fixed key and IV so I could repeat the experiment. In real use the IV should be random and never reused with the same key.

## References

[1] OpenSSL Project, "openssl-enc – symmetric cipher routines," OpenSSL 3.0 manual. [Online]. Available: https://docs.openssl.org/3.0/man1/openssl-enc/. [Accessed: Oct. 18, 2026].
[2] OpenSSL Project, "OSSL_PROVIDER-legacy – OpenSSL legacy provider," OpenSSL 3.0 manual. [Online]. Available: https://docs.openssl.org/3.0/man7/OSSL_PROVIDER-legacy/. [Accessed: Oct. 18, 2026].
[3] K. Bhargavan and G. Leurent, "On the Practical (In-)Security of 64-bit Block Ciphers: Collision Attacks on HTTP over TLS and OpenVPN," in Proc. ACM CCS, 2016.
