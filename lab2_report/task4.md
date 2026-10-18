# Task 4 – Encryption Mode (ECB vs. CBC)

In this task I encrypted the picture pic_original.bmp with AES-128 in two modes, ECB (Electronic Code Book) and CBC (Cipher Block Chaining), and then viewed the encrypted files as pictures to see how much information each mode leaks.

## Encrypting the picture

I used the same key as in Task 3. ECB does not use an IV, so the -iv option is only given for CBC.

    openssl enc -aes-128-ecb -e -in pic_original.bmp -out pic_ecb.bin -K 00112233445566778899aabbccddeeff
    openssl enc -aes-128-cbc -e -in pic_original.bmp -out pic_cbc.bin -K 00112233445566778899aabbccddeeff -iv 0102030405060708090a0b0c0d0e0f10

[IMG 18.png] Figure 19: Encrypting the picture with AES-128-ECB and AES-128-CBC

## Step 1 – Fixing the BMP header

A .bmp file starts with a 54-byte header that holds information like the file type, width, height and colour depth. The eog properties panel shows that the picture is 460 × 134 pixels, and for a normal 24-bit BMP like this one the pixel data starts right after the 54-byte header. After encryption the header is also encrypted, so an image viewer cannot open the file. To be able to view it, I took the first 54 bytes from the original picture and the rest of the data (from byte 55 to the end) from the encrypted file, and joined them together:

    head -c 54 pic_original.bmp > header
    tail -c +55 pic_ecb.bin > body_ecb
    tail -c +55 pic_cbc.bin > body_cbc
    cat header body_ecb > new_ecb.bmp
    cat header body_cbc > new_cbc.bmp

[IMG 19.png] Figure 20: Replacing the header and checking the file sizes

The original file is 184,974 bytes and the encrypted files are 184,976 bytes. The 2 extra bytes are the PKCS#7 padding, because 184,974 is not a multiple of 16 and the next multiple of 16 is 184,976 (16 × 11,561). The new .bmp files are also 184,976 bytes (54 bytes header + 184,922 bytes of encrypted data). The image viewer just ignores the 2 extra bytes at the end because the header says how big the image is.

## Step 2 – Displaying the pictures

I installed eog (Eye of GNOME) and opened the original and both encrypted pictures.

[IMG 20c.png] Figure 21: The original picture
[IMG 21.png] Figure 22: The picture encrypted with ECB mode
[IMG 22.png] Figure 23: The picture encrypted with CBC mode

## Step 3 – Observations

**Original:** a white background with a red ellipse in the middle and a teal rectangle with a blue border at the bottom right.

**ECB:** the colours are changed to a repeating striped pattern, but the shape of the picture is still completely visible. I can clearly see the ellipse, its exact size and position, and the rectangle at the bottom right. Someone without the key can still tell what the picture shows, so ECB fails to hide the information in this picture.

The reason is how ECB works. The data is split into 16-byte blocks and every block is encrypted separately with the same key:

    C_i = E_K(P_i)

So two identical plaintext blocks always give two identical ciphertext blocks. In this picture large areas have the same colour (the white background is all FF FF FF bytes, the ellipse is all red pixels), so many 16-byte blocks are the same and they all become the same ciphertext block. The colours change, but the areas with the same colour stay as areas with the same pattern, and the edges between them stay where they were. The stripes in the background come from the fact that one row of the image is 460 × 3 = 1380 bytes, which is not a multiple of 16, so the blocks do not line up exactly with the rows and the same few ciphertext blocks repeat with a shift from row to row.

**CBC:** the picture looks like random coloured noise. There is no ellipse, no rectangle and no pattern at all. I cannot get any useful information about the original picture from it, only its size, which comes from the header I copied.

In CBC each plaintext block is XORed with the previous ciphertext block before encryption, and the first block is XORed with the IV:

    C_i = E_K(P_i ⊕ C_(i-1)),  C_0 = IV

So even if two plaintext blocks are the same (like two white blocks), the blocks before them are different, so the input to AES is different and the output is different. Every ciphertext block depends on all the previous blocks, so the repeated patterns of the picture are completely hidden.

## Conclusion

This experiment shows that the encryption algorithm alone is not enough, the mode is also very important. Both pictures were encrypted with the same AES-128 cipher and the same key, but ECB leaked the structure of the image while CBC hid it. In my opinion ECB should not be used to encrypt data that is longer than one block, especially data with a lot of repetition such as images, documents with fixed formats, or database records. The same problem is shown in the well-known "ECB penguin" example on Wikipedia [1]. For real use a mode with an IV (like CBC or CTR) or an authenticated mode like GCM should be used instead.

One thing I also noticed is that the header must still be readable to view the picture. In my case I copied it from the original, but in a real attack the attacker could guess it easily, since BMP headers are standard and only the width and height change.

## References

[1] Wikipedia, "Block cipher mode of operation." [Online]. Available: https://en.wikipedia.org/wiki/Block_cipher_mode_of_operation. [Accessed: Oct. 18, 2026].
