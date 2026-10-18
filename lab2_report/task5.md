# Task 5 – Error Propagation – Corrupted Cipher Text

In this task I checked what happens when one bit of the ciphertext gets corrupted and the file is then decrypted with the correct key and IV. I tested AES-128 in four modes: ECB, CBC, CFB and OFB.

## My predictions (before doing the task)

I made these predictions from the decryption formula of each mode [1][2].

The 55th byte is byte number 54 when counting from 0 (offset 0x36). With 16-byte AES blocks, bytes 1–16 are block 1, 17–32 block 2, 33–48 block 3 and 49–64 block 4, so the 55th byte is the 7th byte of block 4.

| Mode | Prediction | Reason |
|---|---|---|
| ECB | Only block 4 (16 bytes) is destroyed, everything else is recovered | Each block is decrypted on its own, P_i = D_K(C_i). A changed C_4 gives a completely different P_4 (avalanche effect of AES), but no other block uses C_4. |
| CBC | Block 4 is destroyed, block 5 has 1 wrong bit at the same position (byte 71), the rest is recovered | P_i = D_K(C_i) ⊕ C_(i-1). C_4 is used twice: in D_K(C_4) for block 4 (whole block destroyed) and in the XOR for block 5 (only the same one bit flips). |
| CFB | Byte 55 has 1 wrong bit, block 5 is destroyed, the rest is recovered | P_i = C_i ⊕ E_K(C_(i-1)). In block 4 the ciphertext is only XORed, so just one bit flips. But C_4 is also the input to AES for the next block, so the key stream for block 5 is completely wrong. |
| OFB | Only 1 bit in byte 55 is wrong, everything else is recovered | The key stream O_i = E_K(O_(i-1)) depends only on the key and IV, not on the ciphertext. So the error stays in the one bit where it happened. |

So my expectation was that in all four modes almost all the file can be recovered and the damage is local, but the amount of damage is different: OFB < ECB < CBC ≈ CFB.

## Step 1 – Creating the file

I created a text file with 70 lines like "Block 001 text." where each line is exactly 16 bytes (15 characters + newline). This way every line is exactly one AES block, so it is easy to see which block is damaged after decryption. The file is 1120 bytes, which is more than the required 1000 bytes.

    for i in $(seq 1 70); do printf "Block %03d text.\n" $i; done > plain.txt

[IMG 23.png] Figure 24: Creating the 1120-byte plaintext file

## Step 2 – Encrypting with AES-128 in four modes

[IMG 24.png] Figure 25: Encryption in ECB, CBC, CFB and OFB modes

The ECB and CBC files are 1136 bytes and the CFB and OFB files are 1120 bytes. Since 1120 is already a multiple of 16, PKCS#7 adds a full extra block of padding (16 bytes) in ECB and CBC. CFB and OFB do not use padding, like I saw in Task 3.

## Step 3 – Corrupting one bit of the 55th byte

The lab says to use the bless hex editor, but bless could not be installed on my Ubuntu 24.04 system ("Unable to locate package bless"). Bless was written in Mono and it is not in the newer Ubuntu repositories anymore.

[IMG 25.png] Figure 26: bless is not available

Instead, I installed GHex, which is another graphical hex editor, and opened ecb.bin. In GHex I could see that the 55th byte (offset 0x36, row 00000030, 7th column) has the value B7.

[IMG 26.png] Figure 27: ecb.bin in GHex, the byte at offset 0x36 is B7

When I tried to edit and save ecb.bin in GHex, the change was not written to the file. When I decrypted all four files at that point, every mode gave 0 different bytes, which showed that the files were still not corrupted (Figure 28). Because of this I flipped the bit with a short Python command instead. It reads the file, XORs byte 54 with 1 (this flips only the lowest bit), and writes it back. It does exactly the same thing as changing B7 to B6 in a hex editor.

[IMG 27_first_run.png] Figure 28: First decryption attempt – 0 bytes differ because the files were not corrupted yet

[IMG t5_flip.png] Figure 29: Checking the corrupted byte (offset 0x36) and the file sizes of all four files

| File | Byte 55 before | Byte 55 after |
|---|---|---|
| ecb.bin | B7 | B6 |
| cbc.bin | 9A | 9B |
| cfb.bin | 59 | 58 |
| ofb.bin | 14 | 15 |

I checked with xxd that only the expected byte changed and with ls -l that the file sizes did not change.

## Step 4 – Decrypting the corrupted files

After all four files were corrupted, I checked the byte at offset 0x36 again and decrypted each file with the correct key and IV. Then I used cmp -l to count how many bytes are different from the original plain.txt, and printed the first lines with cat -v so the non-printable characters can be seen.

[IMG t5_decrypt.png] Figure 30: Checking the corrupted bytes and decrypting the four files

[IMG t5_results.png] Figure 31: Decryption results for ECB, CBC, CFB and OFB

## Results

| Mode | Bytes different | What I saw |
|---|---|---|
| ECB | 16 | Line 4 is completely garbage, all other lines are correct |
| CBC | 17 | Line 4 is completely garbage, line 5 shows "Block 105" instead of "Block 005", the rest is correct |
| CFB | 17 | Line 4 shows "Block 104" instead of "Block 004", line 5 is completely garbage, the rest is correct |
| OFB | 1 | Only line 4 shows "Block 104" instead of "Block 004", everything else is correct |

All my predictions were correct.

- **ECB:** the whole 4th block (bytes 49–64) was destroyed and nothing else. Because AES has the avalanche effect, flipping 1 input bit to the decryption changes about half of the output bits, so the whole block becomes random.
- **CBC:** the 4th block was destroyed for the same reason as ECB. In the 5th block only one character changed, "0" → "1" in "Block 005". This is byte 71, which is exactly 16 bytes after byte 55, and "0" (0x30) → "1" (0x31) is exactly the lowest bit, the same bit I flipped in the ciphertext. This is because C_4 is XORed directly with D_K(C_5). From block 6 the decryption is correct again because C_5 is not damaged. 16 + 1 = 17 bytes.
- **CFB:** it is the opposite order of CBC. In block 4 only one bit flipped ("Block 004" → "Block 104", byte 55, again "0" → "1"), because in CFB the ciphertext is just XORed with the key stream. Then block 5 is completely garbage, because the damaged C_4 was the input to AES to make the key stream for block 5. After that it recovers. 1 + 16 = 17 bytes.
- **OFB:** only one bit in byte 55 was wrong. The key stream does not depend on the ciphertext at all, so a bit error in the ciphertext only gives the same bit error in the plaintext.

## Analysis

Even though CBC and CFB both lose 17 bytes, the pattern is different: CBC destroys the corrupted block and flips one bit in the next, CFB flips one bit in the corrupted block and destroys the next one. The error does not spread further in any of the modes. CBC and CFB are "self-synchronising": after one extra block they recover by themselves.

OFB has the best error propagation, only 1 bit, so it is good for noisy channels such as radio or satellite links. But this also means something negative: an attacker can flip a chosen bit in the ciphertext and the same bit flips in the plaintext without destroying anything else (bit-flipping attack). For example in my file the attacker changed "004" to "104" and the text still looks valid. The same is true for the corrupted block in CFB and for the next block in CBC. This shows that encryption alone does not protect the integrity of the data, and a MAC or an authenticated mode like AES-GCM should be used to detect such changes.

## References

[1] Wikipedia, "Block cipher mode of operation." [Online]. Available: https://en.wikipedia.org/wiki/Block_cipher_mode_of_operation. [Accessed: Oct. 18, 2026].
[2] W. Stallings, Cryptography and Network Security: Principles and Practice, 8th ed. Pearson, 2020.
