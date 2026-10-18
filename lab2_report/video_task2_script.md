# Video – Task 2 (Frequency Analysis) – script, about 4–5 minutes

Before recording:
    cd ~/lab-2
    PS1="\d \@ [1093911] "
    clear

---------------------------------------------------------------
## Part 1 – Intro (≈20 s)
SAY:
"Hello, my name is Mezrait Menber, student ID 1093911, section 103. This is the video for ITE408 Lab 2. I will demonstrate Task 2, frequency analysis, and Task 4, ECB versus CBC. You can see my student ID in the terminal prompt."

---------------------------------------------------------------
## Part 2 – What we have (≈40 s)
RUN:
    ls
    head -5 ciphertext.txt
SAY:
"In Task 2 we are given ciphertext.txt. It was encrypted with a monoalphabetic substitution cipher, which means every letter is always replaced by the same letter. For example if 'e' becomes 'n', then every 'e' in the whole text becomes 'n'.
The spaces are kept, so we can still see the word boundaries.
The weakness of this cipher is that it does not change how often each letter appears. In English, E is the most common letter, then T, A, O, and the most common three-letter word is THE. So if I count the letters in the ciphertext, I can match them with English."

---------------------------------------------------------------
## Part 3 – freq.py (≈60 s)
RUN:
    python3 freq.py | head -25
SAY (point at n):
"freq.py counts single letters, bigrams and trigrams. The most common letter is 'n' with 488, so 'n' is probably E. The second is 'y' with 373, probably T."
RUN:
    python3 freq.py | tail -21
SAY (point at ytn):
"The most common trigram is 'ytn' with 78. That is much more than the second one, which is only 30. In English, THE is by far the most common trigram, so ytn should be THE. This also fits: y is T, n is E, and the top bigrams 'yt' and 'tn' would be TH and HE, which are the two most common English bigrams."

---------------------------------------------------------------
## Part 4 – Stage 1: THE (≈30 s)
RUN:
    tr 'ytn' 'THE' < ciphertext.txt > out.txt && head -5 out.txt
SAY:
"I use the tr command to replace y, t and n with capital T, H, E. I use capitals for letters I already solved, and small letters are still unknown. Now we can see THE appearing many times in the text, so the guess is correct."

---------------------------------------------------------------
## Part 5 – Stage 2: AND, ING (≈40 s)
RUN:
    tr 'ytnvupmr' 'THEANDIG' < ciphertext.txt > out.txt && head -5 out.txt
SAY:
"The second and third trigrams are 'vup' and 'mur'. The next most common English trigrams are AND and ING. vup appears as a separate word, so it is AND. mur appears at the end of words, which is where ING is in English.
Now some words are almost readable, like 'THE END AND IT', and this long word 'NxNAGENAhIAN'."

---------------------------------------------------------------
## Part 6 – Stage 3: word patterns (≈40 s)
RUN:
    tr 'ytnvupmrxqhzd' 'THEANDIGOSRUY' < ciphertext.txt > out.txt && head -8 out.txt
SAY (point at the first line):
"From here I don't need the frequency table much, I can guess from the words.
'xN' is a two-letter word ending with N, so it's ON, x is O.
'qzNDAd' looks like SUNDAY, so q is S, z is U, d is Y.
'hIGHT' is RIGHT, so h is R.
Now the first line says 'THE OSCARS TURN ON SUNDAY', so the article is about the Oscars."

---------------------------------------------------------------
## Part 7 – Stage 4 (≈30 s)
RUN:
    tr 'ytnvupmrxqhzdalgbise' 'THEANDIGOSRUYCWBFLKP' < ciphertext.txt > out.txt && head -8 out.txt
SAY:
"Same idea: OSaARS is OSCARS so a is C, lHIaH is WHICH so l is W, AgOUT is ABOUT so g is B, AbTER is AFTER so b is F, iONG is LONG, iIsE is LIKE and TRIe is TRIP."

---------------------------------------------------------------
## Part 8 – Stage 5: full key (≈40 s)
SAY (before running, point at remaining small letters):
"Only a few letters are left: DEcISE is DEMISE, HARfEY is HARVEY, EjUALLY is EQUALLY, EkTRA is EXTRA, oUST is JUST and PRIwE is PRIZE.
These last letters are Q, X, J and Z, which are the rarest letters in English. They appear only a few times, so the frequency table cannot help with them. They can only be found from the context."
RUN:
    tr 'abcdefghijklmnopqrstuvwxyz' 'CFMYPVBRLQXWIEJDSGKHNAZOTU' < ciphertext.txt > plaintext.txt && head -20 plaintext.txt
SAY:
"This is the full key and the whole article is now readable."

---------------------------------------------------------------
## Part 9 – Conclusion of Task 2 (≈30 s)
SAY:
"So my conclusion is that the monoalphabetic cipher is not secure. The key space is very big, 26 factorial, about 4 times 10 to the 26, so brute force is not possible. But we don't need brute force, because the cipher keeps the letter statistics of English. With only a frequency count and some guessing I recovered the full message in five steps. Keeping the spaces also made it easier, because short words like ON and AND gave strong hints."

→ Then continue to Task 4.
