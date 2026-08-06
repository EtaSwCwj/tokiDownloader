export function selectEpisodeLinks(
    links,
    { metadataOnly = false, scanMode = 'full', startIndex = 0, lastIndex = 99999,
        completedEpisodes = new Set() } = {}
) {
    if (metadataOnly)
        return { links: [], skippedExistingEpisodes: 0 };
    if (scanMode === 'new') {
        const selected = links.filter(item => !completedEpisodes.has(parseInt(item.num)));
        return {
            links: selected,
            skippedExistingEpisodes: links.length - selected.length
        };
    }
    if (scanMode === 'range') {
        return {
            links: links.filter(item => {
                const episodeNumber = parseInt(item.num);
                return startIndex <= episodeNumber && episodeNumber <= lastIndex;
            }),
            skippedExistingEpisodes: 0
        };
    }
    return { links: [...links], skippedExistingEpisodes: 0 };
}
