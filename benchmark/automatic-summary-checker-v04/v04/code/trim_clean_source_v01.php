<?php
declare(strict_types=1);

/* Preparation-only boundary trimmer for publisher-page material after extraction. */

if ($argc !== 3) {
    fwrite(STDERR, "Usage: php trim_clean_source_v01.php FILE EXCLUDED_TAIL_MARKER\n");
    exit(2);
}

[$script, $path, $marker] = $argv;
$text = is_file($path) ? file_get_contents($path) : false;
if ($text === false) {
    fwrite(STDERR, "File is unavailable.\n");
    exit(2);
}

$position = strpos($text, $marker);
if ($position === false) {
    fwrite(STDERR, "Boundary marker was not found.\n");
    exit(2);
}

$trimmed = rtrim(substr($text, 0, $position)) . "\n";
if (mb_strlen($trimmed, 'UTF-8') < 300) {
    fwrite(STDERR, "Trimmed article is implausibly short.\n");
    exit(2);
}

if (file_put_contents($path, $trimmed) === false) {
    fwrite(STDERR, "Trimmed article could not be saved.\n");
    exit(2);
}

fwrite(STDOUT, "TRIMMED\t" . basename($path) . "\t" . mb_strlen($trimmed, 'UTF-8') . " characters\n");

