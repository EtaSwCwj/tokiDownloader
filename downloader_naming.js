const DEFAULT_FOLDER_TEMPLATE = '[{author}][{group}] {title}';
const ALLOWED_FOLDER_FIELDS = new Set(['author', 'group', 'title', 'site', 'id']);
const WINDOWS_INVALID_PATH_CHARS = /[<>:"/\\|?*\u0000-\u001F]/;
const WINDOWS_RESERVED_NAMES = /^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$/i;

function sanitizePathSegment(value, fallback = 'N／A') {
    const sanitized = String(value ?? '')
        .replace(/[<>:"/\\|?*\u0000-\u001F]/g, '')
        .replace(/[. ]+$/g, '')
        .trim();
    const candidate = sanitized || fallback;
    return WINDOWS_RESERVED_NAMES.test(candidate) ? `_${candidate}` : candidate;
}

function validateFolderTemplate(value) {
    const template = String(value ?? '').trim();
    if (!template)
        throw new Error('작품 폴더명 템플릿을 입력해주세요.');
    if (template.length > 180)
        throw new Error('작품 폴더명 템플릿은 180자 이하여야 합니다.');

    const withoutFields = template.replace(/\{([a-zA-Z][a-zA-Z0-9_]*)\}/g, (_match, field) => {
        if (!ALLOWED_FOLDER_FIELDS.has(field))
            throw new Error(`지원하지 않는 폴더명 변수입니다: {${field}}`);
        return '';
    });
    if (/[{}]/.test(withoutFields))
        throw new Error('폴더명 변수는 {author}, {group}, {title}, {site}, {id} 형식으로 입력해주세요.');
    if (WINDOWS_INVALID_PATH_CHARS.test(withoutFields))
        throw new Error('폴더명 템플릿의 고정 문자에 Windows 금지 문자를 사용할 수 없습니다.');
    if (!template.includes('{title}'))
        throw new Error('작품을 구분할 수 있도록 {title} 변수가 필요합니다.');
    return template;
}

function renderFolderTemplate(value, metadata = {}) {
    const template = validateFolderTemplate(value || DEFAULT_FOLDER_TEMPLATE);
    const source = metadata.source || {};
    const values = {
        author: sanitizePathSegment(metadata.author),
        group: sanitizePathSegment(metadata.group),
        title: sanitizePathSegment(metadata.title, '제목 없음'),
        site: sanitizePathSegment(source.siteTitle || metadata.site || source.site),
        id: sanitizePathSegment(source.workId || metadata.id),
    };
    const rendered = template.replace(/\{([a-zA-Z][a-zA-Z0-9_]*)\}/g, (_match, field) => values[field]);
    if (!rendered || rendered.length > 240)
        throw new Error('미리보기 폴더명이 비어 있거나 Windows 안전 길이 240자를 초과합니다.');
    if (WINDOWS_INVALID_PATH_CHARS.test(rendered) || /[. ]$/.test(rendered))
        throw new Error('미리보기 폴더명이 Windows 경로 규칙에 맞지 않습니다.');
    if (WINDOWS_RESERVED_NAMES.test(rendered))
        throw new Error('Windows 예약 장치 이름은 폴더명으로 사용할 수 없습니다.');
    return rendered;
}

export {
    ALLOWED_FOLDER_FIELDS,
    DEFAULT_FOLDER_TEMPLATE,
    renderFolderTemplate,
    sanitizePathSegment,
    validateFolderTemplate,
};
