# Data Sources

The Daily SEO Reviewer analyzes publicly accessible website data to identify technical SEO issues and generate prioritized recommendations.

## 1. Website Crawl Data

**Source:** The target website, retrieved through HTTP requests and HTML parsing.

**Data collected:**
- Page URLs and HTTP response status codes
- Page titles and meta descriptions
- Heading structure (H1–H6)
- Canonical URLs and robots directives
- Internal links
- Other SEO-relevant HTML elements

**Purpose:** Identify technical and on-page SEO issues, such as missing metadata, broken links, and potential indexing problems.

## 2. PageSpeed Insights Data

**Source:** Google PageSpeed Insights API.

**Data collected:**
- Lighthouse performance and SEO scores
- Core Web Vitals and other performance metrics
- Diagnostic findings and optimization opportunities

**Purpose:** Detect performance-related issues and identify areas for improvement.

## 3. Historical Review Data

**Source:** Results stored locally from previous agent runs.

**Purpose:** Compare current findings with previous reviews, identify new or resolved issues, and avoid repeatedly reporting unchanged problems.

