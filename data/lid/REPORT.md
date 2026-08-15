# LID model report

char 1-4gram TF-IDF + logistic regression, trained on VarDial 2018 ILI
(train+dev = 80680 sentences), evaluated on the shared-task gold set.

**Test accuracy: 0.8786** (9692 sentences)

```
              precision    recall  f1-score   support

         AWA      0.962     0.686     0.801      1502
         BHO      0.787     0.926     0.850      2006
         BRA      0.864     0.979     0.918      2147
         HIN      0.867     0.809     0.837      1835
         MAG      0.965     0.927     0.946      2202

    accuracy                          0.879      9692
   macro avg      0.889     0.865     0.870      9692
weighted avg      0.887     0.879     0.877      9692

```

## Corpus audit (fraction of lines classified per language)

| file | lines | BHO | HIN | AWA | BRA | MAG |
|---|---:|---:|---:|---:|---:|---:|
| all-dedup.txt | 50000 | 97% | 3% | 0% | 0% | 0% |
| bhltr-mono-NC.txt | 36761 | 98% | 2% | 0% | 0% | 0% |
| bhwiki.txt | 25352 | 95% | 4% | 0% | 1% | 0% |
| finepdfs.txt | 50000 | 80% | 14% | 1% | 3% | 3% |
| fineweb2.txt | 50000 | 96% | 2% | 0% | 1% | 1% |
| hplt.txt | 50000 | 93% | 3% | 0% | 1% | 2% |
| madlad-clean.txt | 50000 | 94% | 4% | 0% | 1% | 0% |
| madlad-noisy.txt | 50000 | 89% | 7% | 0% | 1% | 1% |
| ud-bhtb.txt | 259 | 97% | 0% | 0% | 1% | 2% |
| vardial-bho.txt | 17726 | 99% | 1% | 0% | 0% | 0% |
