# Task 2 – Frequency Analysis

In this task I was given ciphertext.txt, which was encrypted with a monoalphabetic substitution cipher using a key I do not know. The goal was to recover the original English text using frequency analysis. The idea is simple: a monoalphabetic cipher changes the letters but it does not change how often each letter appears. So the most common letter in the ciphertext is probably the most common letter in English (E), the most common three-letter group is probably THE, and so on [1][2][3].

To keep track of my progress I wrote the plaintext letters in CAPITALS and left the unknown ciphertext letters in small letters, as the lab suggested. Every stage starts again from the original ciphertext.txt and the tr command gets longer as I learn more letters.

## Stage 0 – Running freq.py

First I ran the provided freq.py program. It prints the top 20 single letters (1-grams), bigrams (2-grams) and trigrams (3-grams) in the ciphertext. It ignores groups that contain spaces.

[IMG 6.png] Figure 6: freq.py output – single letter and bigram frequencies
[IMG 7.png] Figure 7: freq.py output – bigram and trigram frequencies

The most important results were:

| Rank | 1-gram | 2-gram | 3-gram |
|---|---|---|---|
| 1 | n (488) | yt (115) | ytn (78) |
| 2 | y (373) | tn (89) | vup (30) |
| 3 | v (348) | mu (74) | mur (20) |
| 4 | x (291) | nh (58) | ynh (18) |
| 5 | u (280) | vh (57) | xzy (16) |

In typical English text the most common letters are E, T, A, O, I, N, the most common bigrams are TH, HE, IN, ER, AN and the most common trigrams are THE, AND, ING [1][2][3]. The ciphertext statistics fit this pattern very well.

## Stage 1 – ytn → THE

The trigram ytn appears 78 times, far more than any other trigram (the second one only appears 30 times). In English THE is by far the most common trigram, so I guessed y→T, t→H, n→E. This guess is also supported by the other statistics: n is the most common single letter (E is the most common in English), y is the second most common (T is second in English), and yt and tn are the two most common bigrams, which match TH and HE.

    tr 'ytn' 'THE' < ciphertext.txt > out.txt && head -5 out.txt

[IMG 8.png] Figure 8: Stage 1 – after replacing ytn with THE

After this step, THE appears in many places in the text, which shows the guess is correct.

## Stage 2 – vup → AND and mur → ING

The second and third most common trigrams are vup (30) and mur (20). The next most common English trigrams are AND and ING. I chose vup→AND because v is the third most common letter (A is third in English) and vup often appears as a separate word between other words. mur→ING because mur appears at the end of words, which is where ING usually is in English. This gives v→A, u→N, p→D, m→I, r→G.

    tr 'ytnvupmr' 'THEANDIG' < ciphertext.txt > out.txt && head -5 out.txt

[IMG 9.png] Figure 9: Stage 2 – after adding AND and ING

Now real words started to appear, for example "THE END AND IT" and "NxNAGENAhIAN".

## Stage 3 – guessing from partly decrypted words

From this point I mostly used word patterns instead of the frequency table:

- "xN" is a two-letter word ending in N, so it is most likely ON → x→O. This also matches x being the 4th most common letter (O is 4th in English).
- "qzNDAd" looks like SUNDAY → q→S, z→U, d→Y.
- "hIGHT" could be RIGHT, LIGHT, MIGHT or FIGHT. I chose R because h is very common (235) and the bigrams nh (58) and hn (57) would then be ER and RE, which are among the most common English bigrams → h→R.

    tr 'ytnvupmrxqhzd' 'THEANDIGOSRUY' < ciphertext.txt > out.txt && head -8 out.txt

[IMG 10.png] Figure 10: Stage 3 – after adding O, S, R, U, Y

The first line now reads "THE OSaARS TURN ON SUNDAY lHIaH SEEcS AgOUT RIGHT AbTER THIS iONG STRANGE". It is clear that this is an article about the Oscars.

## Stage 4 – more letters from the context

- "OSaARS" → OSCARS, so a→C
- "lHIaH" → WHICH, so l→W
- "AgOUT" → ABOUT, so g→B
- "AbTER" → AFTER, so b→F
- "iONG" → LONG, so i→L
- "iIsE" → LIKE, so s→K
- "TRIe" → TRIP, so e→P

    tr 'ytnvupmrxqhzdalgbise' 'THEANDIGOSRUYCWBFLKP' < ciphertext.txt > out.txt && head -8 out.txt

[IMG 11.png] Figure 11: Stage 4 – after adding C, W, B, F, L, K, P

## Stage 5 – the remaining letters and the full key

Only a few small letters were left in the text and they were easy to guess from the words they are in:

- "DEcISE" → DEMISE, so c→M
- "HARfEY" → HARVEY (Harvey Weinstein), so f→V
- "EjUALLY" → EQUALLY, so j→Q
- "EkTRA" → EXTRA, so k→X
- "oUST" → JUST, so o→J
- "PRIwE" → PRIZE, so w→Z

These letters (Q, X, J, Z) are the least common letters in English, and that is why they were the last ones to be found: they appear only a few times, so the frequency table gives almost no information about them and they can only be found from the context of the words.

The final key is:

| Ciphertext | a | b | c | d | e | f | g | h | i | j | k | l | m | n | o | p | q | r | s | t | u | v | w | x | y | z |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Plaintext  | C | F | M | Y | P | V | B | R | L | Q | X | W | I | E | J | D | S | G | K | H | N | A | Z | O | T | U |

    tr 'abcdefghijklmnopqrstuvwxyz' 'CFMYPVBRLQXWIEJDSGKHNAZOTU' < ciphertext.txt > plaintext.txt && cat plaintext.txt

[IMG 12.png] Figure 12: Stage 5 – the fully decrypted article

The decrypted text is a news article about the Oscars and the #MeToo / Times Up movement: "THE OSCARS TURN ON SUNDAY WHICH SEEMS ABOUT RIGHT AFTER THIS LONG STRANGE AWARDS TRIP …". The whole text reads as correct English, so the key is correct.

## Observations and analysis

- Frequency analysis worked very well because the text is long (4759 characters). In a short text like my one-paragraph article from Task 1 the statistics would be less reliable and it would take more guessing.
- The trigram ytn (78) was much more useful than the single letter frequencies. For example the single letters x (291), u (280) and q (276) have very close counts, so I could not be sure which one is O, N or S only from the letter count. But one trigram that stands out so clearly gives three letters at once.
- Keeping the spaces made the attack much easier. Short words like "xN" (ON) and "vup" (AND) give strong hints. If the spaces were removed it would still be possible but harder.
- In some places there are double spaces, for example "AMASSED  MILLION" and "DONATIONS OF  OR LESS". This is because the numbers (like dollar amounts) were deleted from the original article before encryption, the same way digits were removed in Task 1.
- My conclusion is that a monoalphabetic substitution cipher is not secure, even though the key space is very big (26! ≈ 4 × 10^26 keys, so brute force is not practical). The problem is that it keeps the statistical structure of the language, so an attacker does not need to try all the keys. I only needed the frequency table and some guessing to recover the full message in a few steps.

## References

[1] Wikipedia, "Frequency analysis." [Online]. Available: https://en.wikipedia.org/wiki/Frequency_analysis. [Accessed: Oct. 18, 2026].
[2] Wikipedia, "Bigram." [Online]. Available: https://en.wikipedia.org/wiki/Bigram. [Accessed: Oct. 18, 2026].
[3] Wikipedia, "Trigram." [Online]. Available: https://en.wikipedia.org/wiki/Trigram. [Accessed: Oct. 18, 2026].
