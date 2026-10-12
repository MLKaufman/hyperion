# RNA-seq Markdown report

This is a **synthetic example** showing how Hyperion displays Markdown alongside HTML reports.

## Analysis summary

Both demonstration samples passed quality control. These values are illustrative, not experimental results.

| Sample | Reads | Status |
| --- | ---: | --- |
| S01 | 24 million | Pass |
| S02 | 28 million | Pass |

## Supporting results

- [Results table](tables/results.csv)
- [HTML analysis report](report.html)
- [Quality-control report](qc.html)

## Example code

```r
results <- read.csv("tables/results.csv")
head(results)
```

> Markdown reports support headings, lists, tables, links, and code blocks.

## Next steps

1. Review the sample quality-control results.
2. Compare findings in the HTML report.
3. Download the project to keep all published results together.

---

Use the **left/right arrows** to change reports and **up/down arrows** to page through this report.
