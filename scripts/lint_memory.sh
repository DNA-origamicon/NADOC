#!/usr/bin/env bash
set -u

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

errors=0
warnings=0

error() {
    printf 'ERROR: %s\n' "$*"
    errors=$((errors + 1))
}

warn() {
    printf 'WARN:  %s\n' "$*"
    warnings=$((warnings + 1))
}

for file in memory/*.md; do
    base=$(basename "$file")
    case "$base" in
        MEMORY.md|*_archive.md)
            continue
            ;;
    esac

    lines=$(wc -l < "$file")
    if (( lines > 1000 )); then
        error "$file is $lines lines; active heads over 1,000 lines must be split immediately"
    elif (( lines > 200 )); then
        warn "$file is $lines lines; target is 200 lines or fewer"
    fi

    status=$(sed -n '1,25p' "$file" | sed -n 's/^status:[[:space:]]*//p' | head -1)
    authority=$(sed -n '1,25p' "$file" | sed -n 's/^authority:[[:space:]]*//p' | head -1)
    review_after=$(sed -n '1,25p' "$file" | sed -n 's/^review_after:[[:space:]]*//p' | head -1)
    if [[ -n "$status" && ! "$status" =~ ^(active|blocked|shipped|retired|historical)$ ]]; then
        error "$file has invalid status '$status'"
    fi
    if [[ -n "$authority" && ! "$authority" =~ ^(canonical|supporting)$ ]]; then
        error "$file has invalid authority '$authority'"
    fi
    if [[ -n "$review_after" && ! "$review_after" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
        error "$file has invalid review_after '$review_after'; expected YYYY-MM-DD"
    fi
    if [[ -n "$status" && -z "$authority" ]]; then
        error "$file declares status but not authority"
    fi

    case "$base" in
        project_*.md|feedback_*.md|REFERENCE_*.md)
            stem=${base%.md}
            short=${stem#project_}
            short=${short#feedback_}
            short=${short#REFERENCE_}
            if ! rg -qi -F "$short" memory/MEMORY.md; then
                error "$file has no discoverable entry in memory/MEMORY.md"
            fi
            ;;
    esac
done

mapfile -t link_sources < <(find memory -maxdepth 1 -type f -name '*.md' ! -name '*_archive.md' -print | sort)
link_sources=(CLAUDE.md MEMORY.md "${link_sources[@]}")

while IFS=: read -r source raw; do
    target=${raw#*](}
    target=${target%)}
    target=${target%%#*}
    case "$target" in
        ''|http://*|https://*|/*)
            continue
            ;;
    esac
    source_dir=$(dirname "$source")
    if [[ ! -e "$source_dir/$target" ]]; then
        error "$source links to missing target $target"
    fi
done < <(rg -o '\]\([^)]*\.md(?:#[^)]*)?\)' "${link_sources[@]}" || true)

if rg -q '\[\[[^]]+\]\]' memory/MEMORY.md; then
    error "memory/MEMORY.md contains wiki-style links; use resolvable Markdown links"
fi

printf 'memory hygiene: %d error(s), %d warning(s)\n' "$errors" "$warnings"
(( errors == 0 ))
