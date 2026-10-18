# Video – Task 4 (ECB vs CBC) – script, about 4 minutes

Before recording:
    cd ~/lab-2
    PS1="\d \@ [1093911] "
    clear

---------------------------------------------------------------
## Part 1 – Intro of Task 4 (≈20 s)
SAY:
"Now Task 4. The goal is to encrypt a picture with AES in two modes, ECB and CBC, and then look at the encrypted picture to see if it still leaks information."

---------------------------------------------------------------
## Part 2 – The original picture (≈20 s)
RUN:
    eog pic_original.bmp &
SAY:
"This is the original picture: a white background, a red ellipse and a teal rectangle. It is 460 by 134 pixels."
(close the window)

---------------------------------------------------------------
## Part 3 – Encrypting (≈40 s)
RUN:
    openssl enc -aes-128-ecb -e -in pic_original.bmp -out pic_ecb.bin -K 00112233445566778899aabbccddeeff
    openssl enc -aes-128-cbc -e -in pic_original.bmp -out pic_cbc.bin -K 00112233445566778899aabbccddeeff -iv 0102030405060708090a0b0c0d0e0f10
SAY:
"I encrypt the same picture with the same AES-128 key, once in ECB and once in CBC. ECB has no IV, CBC needs a 16-byte IV. So the only difference between the two files is the mode."

---------------------------------------------------------------
## Part 4 – Fixing the header (≈50 s)
RUN:
    head -c 54 pic_original.bmp > header
    tail -c +55 pic_ecb.bin > body_ecb
    tail -c +55 pic_cbc.bin > body_cbc
    cat header body_ecb > new_ecb.bmp
    cat header body_cbc > new_cbc.bmp
    ls -l pic_original.bmp new_ecb.bmp new_cbc.bmp
SAY:
"A BMP file starts with a 54-byte header that tells the viewer the size and format of the image. After encryption the header is also encrypted, so the image viewer cannot open the file. So I take the first 54 bytes from the original file with head, and the encrypted data from byte 55 to the end with tail, and join them with cat.
The original is 184,974 bytes and the encrypted ones are 184,976. The 2 extra bytes are padding, because AES works on 16-byte blocks."

---------------------------------------------------------------
## Part 5 – Viewing the encrypted pictures (≈50 s)
RUN:
    eog new_ecb.bmp &
SAY (point at the ellipse and rectangle):
"This is the ECB picture. The colours changed into a striped pattern, but I can still clearly see the ellipse and the rectangle, in the same place and the same size. So someone without the key still knows what the picture shows. ECB failed to hide the information."
RUN:
    eog new_cbc.bmp &
SAY:
"This is the CBC picture. It is just random noise, there is no shape at all. I cannot get any information about the original, only the size, and that is only because I copied the header."

---------------------------------------------------------------
## Part 6 – Proof: repeated blocks (≈40 s)
RUN:
    xxd -s 64 -l 96 pic_ecb.bin
    xxd -s 64 -l 96 pic_cbc.bin
SAY:
"Here we can see why. In the ECB file, these six lines are exactly the same, because they come from the white background, and the same plaintext block always gives the same ciphertext block. In the CBC file, the same white blocks give completely different ciphertext."
RUN:
    python3 -c "import sys
for f in sys.argv[1:]:
    d=open(f,'rb').read(); b=[d[i:i+16] for i in range(0,len(d),16)]
    print(f, len(b), 'blocks,', len(set(b)), 'unique')" pic_ecb.bin pic_cbc.bin
SAY:
"And if I count: the ECB file has 11,561 blocks but only 47 different ones. The CBC file has 11,561 blocks and all of them are different."

---------------------------------------------------------------
## Part 7 – Explanation and conclusion (≈50 s)
SAY:
"The reason is how the modes work.
In ECB, every 16-byte block is encrypted separately with the same key. So identical plaintext blocks become identical ciphertext blocks. The picture has big areas with the same colour, so the pattern stays.
In CBC, each plaintext block is XORed with the previous ciphertext block before encryption, and the first block is XORed with the IV. So even if two blocks are the same, the input to AES is different, and the output is different.
My conclusion is that the cipher alone is not enough. It's the same AES and the same key, but ECB leaked the picture and CBC did not. So ECB should not be used for data with repeated patterns. A mode with an IV like CBC, or better an authenticated mode like GCM, should be used.
Thank you for watching."
