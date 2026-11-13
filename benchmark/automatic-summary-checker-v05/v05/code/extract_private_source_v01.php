<?php
declare(strict_types=1);

/*
 * Preparation-only HTML-to-text helper.
 *
 * Usage:
 *   php extract_private_source_v01.php INPUT_HTML XPATH OUTPUT_TEXT
 *
 * The caller supplies an XPath narrowed to the publisher's article container.
 * This prevents a generic whole-page scrape from being mistaken for a verified
 * complete article. The output is deliberately plain text so it can be reviewed
 * before it is admitted to the frozen evidence bundle.
 */

if ($argc !== 4) {
    fwrite(STDERR, "Usage: php extract_private_source_v01.php INPUT_HTML XPATH OUTPUT_TEXT\n");
    exit(2);
}

[$script, $inputPath, $xpathExpression, $outputPath] = $argv;

if (!is_file($inputPath)) {
    fwrite(STDERR, "Input does not exist.\n");
    exit(2);
}

$html = file_get_contents($inputPath);
if ($html === false || trim($html) === '') {
    fwrite(STDERR, "Input is empty or unreadable.\n");
    exit(2);
}

$previous = libxml_use_internal_errors(true);
$document = new DOMDocument();
$loaded = $document->loadHTML($html, LIBXML_NONET | LIBXML_NOERROR | LIBXML_NOWARNING);
libxml_clear_errors();
libxml_use_internal_errors($previous);

if (!$loaded) {
    fwrite(STDERR, "HTML could not be parsed.\n");
    exit(2);
}

$xpath = new DOMXPath($document);
$nodes = $xpath->query($xpathExpression);
if ($nodes === false || $nodes->length !== 1) {
    fwrite(STDERR, "XPath must match exactly one article container; matched " . ($nodes === false ? 'ERROR' : (string) $nodes->length) . ".\n");
    exit(2);
}

$container = $nodes->item(0);
if (!$container instanceof DOMNode) {
    fwrite(STDERR, "Article container is unavailable.\n");
    exit(2);
}

foreach (['script', 'style', 'noscript', 'svg', 'form', 'nav', 'footer', 'aside', 'button'] as $tag) {
    $remove = [];
    foreach (($container instanceof DOMElement ? $container->getElementsByTagName($tag) : []) as $candidate) {
        $remove[] = $candidate;
    }
    foreach ($remove as $candidate) {
        if ($candidate->parentNode !== null) {
            $candidate->parentNode->removeChild($candidate);
        }
    }
}

$text = html_entity_decode((string) $container->textContent, ENT_QUOTES | ENT_HTML5, 'UTF-8');
$text = preg_replace('/[\t\x0B\f\r ]+/u', ' ', $text) ?? $text;
$text = preg_replace('/ *\n */u', "\n", $text) ?? $text;
$text = preg_replace('/\n{3,}/u', "\n\n", $text) ?? $text;
$text = trim($text) . "\n";

if (mb_strlen($text, 'UTF-8') < 300) {
    fwrite(STDERR, "Extracted article is implausibly short.\n");
    exit(2);
}

if (file_put_contents($outputPath, $text) === false) {
    fwrite(STDERR, "Output could not be written.\n");
    exit(2);
}

fwrite(STDOUT, "EXTRACTED\t" . basename($inputPath) . "\t" . mb_strlen($text, 'UTF-8') . " characters\n");

