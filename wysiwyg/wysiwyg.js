import {Img, ValidityError, Alarms, tick} from '/all.js';

export const Wysiwyg = {}

// БАЗОВЫЕ МЕТОДЫ, КОТОРЫЕ НУЖНЫ ДАЖЕ В САМЫХ ПРОСТЫХ КОНТЕНТЭДИТАБЛАХ, НАПРИМЕР — В ПОЛЕ ЗАГОЛОВКА

Wysiwyg.prevent_default_formatting = function(e, contenteditable) {
    // https://stackoverflow.com/questions/48790160/contenteditable-keyboard-shortcuts

    if (e.metaKey && ['KeyB', 'KeyI', 'KeyU'].includes(e.code)) {
        e.preventDefault();
    }
}

Wysiwyg.process_paste = async function(e, contenteditable, create_pars=false, allow_files=false) {
    // https://stackoverflow.com/a/6804718/4117781

    e.preventDefault();

    const clipboard_data = e.clipboardData || window.clipboardData;
    const data = clipboard_data.getData('text/plain');
    const files = clipboard_data.files;

    if (data) {
        remove_selected_contents();  // Если было какое-то выделение — удаляем его перед вставкой текста
        const normalized_data = normalize_spaces(data);

        // Создадим пустые строки, если курсор|выделение в блоке с картинкой
        if (create_pars) {
            const range = document.getSelection().getRangeAt(0);
            const start_par = ensure_par(range.startContainer);
            const end_par = ensure_par(range.endContainer);
            const start_par_has_img = start_par.querySelector('img');
            const end_par_has_img = end_par.querySelector('img');
            if (start_par_has_img || end_par_has_img) {
                if (range.endOffset === 0) {
                    // Курсор (или выделение) СЛЕВА от картинки
                    const new_par = create_par({before: end_par, br: true});
                    set_focus(new_par, 'START');
                } else if (range.startOffset === 1) {
                    // Курсор (или выделение) СПРАВА от картинки
                    const new_par = create_par({after: start_par, br: true});
                    set_focus(new_par, 'START');
                }
            }
        }
        // Конец "Создадим пустые строки, если курсор|выделение в блоке с картинкой"

        document.execCommand('insertHTML', false, normalized_data);
    } else if (files.length && allow_files) {
        await process_files(e, contenteditable, files);
    }
}

// ДЛЯ БЛОКОВЫХ КОНТЕНТЭДИТАБЛОВ

Wysiwyg.ensure_at_least_empty_par = function(e, contenteditable) {
    if (['', '<br>'].includes(contenteditable.innerHTML.trim())) {
        contenteditable.innerHTML = '<div><br></div>'
    }
}

// ДЛЯ ВУСИВУГА

Wysiwyg.prevent_input_in_image_block = function(e, contenteditable) {

    const range = document.getSelection().getRangeAt(0);
    const start_par = get_par(range.startContainer);
    const end_par = get_par(range.endContainer);
    const start_par_has_img = start_par?.querySelector('img');
    const end_par_has_img = end_par?.querySelector('img');

    // Если картинок нет ни с одного из концов (в т.ч. выделения) — валим отсюда
    if (!start_par_has_img && !end_par_has_img) {
        return;
    }

    if (e.key.length === 1 && !e.metaKey) {
        // Если обычный ввод https://stackoverflow.com/questions/4179708/
        if (range.endOffset === 0) {
            // Курсор (или выделение) СЛЕВА от картинки
            const new_par = create_par({before: end_par, br: true});
            set_focus(new_par, 'START');
        } else if (range.startOffset === 1) {
            // Курсор (или выделение) СПРАВА от картинки
            const new_par = create_par({after: start_par, br: true});
            set_focus(new_par, 'START');
        }
    } else if (e.code === 'Backspace') {
        // Позволяем отработать нативно:
        // - Стереть верхнюю строку (если СЛЕВА) или
        // - Стереть картинку (если СПРАВА)
        // pass
    } else if (e.code === 'Enter' && !e.shiftKey) {
        // Позволяем отработать нативно:
        // - Создать строку сверху, не перемещая на неё курсор (если СЛЕВА) или
        // - Создать строку снизу, перемещая на неё курсор (если СПРАВА)
        // pass
    } else if (e.code === 'Enter' && e.shiftKey) {
        // Нативно, Shift + Enter создаёт пустую строку внутри блока с изображением.
        // И это не то что нам нужно.
        // Эмулируем Shift + Enter как обычный Enter
        e.preventDefault();
        if (range.endOffset === 0) {
            // Курсор (или выделение) СЛЕВА от картинки
            const new_par = create_par({before: end_par, br: true});
        } else if (range.startOffset === 1) {
            // Курсор (или выделение) СПРАВА от картинки
            const new_par = create_par({after: start_par, br: true});
            set_focus(new_par, 'START');
        }
    } else if (e.code === 'Tab') {
        // Табуляцию в случае изображения — просто игнорируем
        e.preventDefault();
    } else if (e.code === 'Delete') {
        // TODO: Пока не понятно, нужен комп с виндой
    }
}

Wysiwyg.ensure_if_last_par_is_image_it_has_par_after = function(e, contenteditable) {
    const contenteditable_children = [...contenteditable.childNodes];  // Чтобы можно было слайсить
    if (contenteditable_children.at(-1).querySelector('img')) {
        const new_par = create_par({after: contenteditable_children.at(-1), br: true});
    }
}

Wysiwyg.handle_tab = function(e, contenteditable) {
    if (e.code === 'Tab') {

        e.preventDefault();

        const lines = [];
        const selected_text = document.getSelection().toString().split('\n');

        if (!e.shiftKey) {
            for (const piece_of_text of selected_text) {
                lines.push('&nbsp; &nbsp; ' + piece_of_text);
            }
        } else {
            for (const piece_of_text of selected_text) {
                const piece_of_text_untabbed = piece_of_text.replace('\u00a0 \u00a0 ', '');  // https://stackoverflow.com/a/1496863/4117781
                lines.push(piece_of_text_untabbed);
            }
        }
        const result = lines.join('');
        document.execCommand('insertHTML', false, result);
    }
}

// ГОРЫ

Wysiwyg.consider_offer_to_load_images = async function(e, contenteditable, data_obj) {
    const selection = document.getSelection();
    if (selection.rangeCount === 0)
        return;
    const range = selection.getRangeAt(0);

    const par = get_par(range.startContainer);

    if (!has_content(par)) {
        data_obj.floating_panel_offered = true;
        data_obj.update();
        await tick();
        data_obj.floating_panel.style.top = (par?.offsetTop || 0).toString() + 'px';
    } else {
        data_obj.floating_panel_offered = false;
        data_obj.update();
    }
}

Wysiwyg.remove_offer_to_load_images = function(e, contenteditable, data_obj) {
    data_obj.floating_panel_offered = false;
    data_obj.update();
}

Wysiwyg.load_images_via_mountains = async function(e, contenteditable, data_obj) {
    await process_files(e, contenteditable, e.currentTarget.files);

    // Обязательно.
    // Иначе возможен кейс, когда пользователь загрузил одну и ту же картинку дважды,
    // и тогда это не будет провоцировать on:change, соответственно в этот метод мы не попадём.
    e.target.value = '';

    // Курсор смещается — нужно пересмотреть предложение
    await Wysiwyg.consider_offer_to_load_images(e, contenteditable, data_obj);
}

// ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ

async function process_files(e, contenteditable, input_files) {
    const range = document.getSelection().getRangeAt(0);

    const files = [...input_files];

    let cur_par = ensure_par(range.startContainer);
    for (const [index, file] of files.entries()) {

        const image = await process_file(e, contenteditable, file);

        if (index === 0 && !has_content(cur_par)) {
            cur_par.innerHTML = '';  // Убираем br-ку
        } else {
            const new_par = create_par({after: cur_par, br: false});
            cur_par = new_par;
        }

        cur_par.appendChild(image);
        cur_par = create_par({after: cur_par, br: true});
    }
    set_focus(cur_par, 'END');

    // В случае с файлами — oninput не триггерится. Сделаем это сами для дальнейших обработок.
    contenteditable.dispatchEvent(new Event('input'));
}

async function process_file(e, contenteditable, file) {
    const img = await Img.to_jpg_if_new_format(file);
    const src = URL.createObjectURL(img);
    const image = new Image();
    image.src = src;

    try {
        await Img.validate(file, image);
    } catch (err) {
        if (err instanceof ValidityError) {
            Alarms.upset(err.message)
        } else {
            throw err;
        }
    }

    return image;
}

function is_par(container) {
    if (
        container instanceof HTMLDivElement && !container.attributes.length
    ) {
        return true
    } else {
        return false
    }
}

function get_par(container) {
    // И в ФФ и в Хроме в range.XXXContainer может ссылаться на текстовую ноду, хотя она и в параграфе.
    // Тут мы гарантируем параграф.

    // Всё чётко
    if (is_par(container)) {
        return container;
    }

    // Текстовая нода в параграфе
    if (container.parentElement && is_par(container.parentElement)) {
        return container.parentElement;
    }

    // Текстовая нода в каком-нибудь <b></b>, а потом в параграфе
    if (container.parentElement?.parentElement && is_par(container.parentElement?.parentElement)) {
        return container.parentElement?.parentElement;
    }

    return null;
}

function ensure_par(container) {
    const par = get_par(container);

    if (par) {
        return par;
    }

    let new_par;

    // Текстовая нода НЕ в параграфе, а лежит просто в КЕ — создадим параграф
    if (container.parentElement.isContentEditable) {
        new_par = create_par({wrap: container});
    }

    // Текстовая нода НЕ в параграфе, но во что-то обёрнута — заменим на параграф
    if (!container.parentElement.isContentEditable) {
        new_par = create_par({replace: container.parentElement});
    }

    return new_par;
}

function create_par({before=null, after=null, replace=null, wrap=null, br=false}={}) {
    const node = before || after || wrap || replace;

    const new_par = document.createElement('div');
    if (br) {
        const br = document.createElement('br');
        new_par.appendChild(br);
    }

    if (wrap) {
        new_par.appendChild(node.cloneNode(true));
        wrap.replaceWith(new_par);
    } else {
        const par = node;
        if (before) {
            par.before(new_par);
        } else if (after) {
            par.after(new_par);
        } else if (replace) {  // НЕ ПРОВЕРЕНО
            const child_nodes = [...par.childNodes];
            for (const child_node of child_nodes) {
                new_par.appendChild(child_node.cloneNode(true));
            }
            par.replaceWith(new_par);
        }
    }

    return new_par;
}

function set_focus(container, focus=['START', 'END'][0]) {
    const selection = document.getSelection();
    const range = selection.getRangeAt(0);

    const par = ensure_par(container);

    const child_nodes = [...par.childNodes || []];
    const last_node = (focus === 'START') ? child_nodes[0] : child_nodes.at(-1);
    const node_to_focus = last_node || par;

    let offset;
    if (node_to_focus instanceof Element) {
        offset = 0;
    } else {
        offset = (focus === 'START') ? 0 : node_to_focus.length;
    }

    range.setStart(node_to_focus, offset);
    range.setEnd(node_to_focus, offset);

    if (focus === 'START') {
        selection.setBaseAndExtent(node_to_focus, offset, range.endContainer, range.endOffset)
    } else if (focus === 'END') {
        selection.setBaseAndExtent(node_to_focus, offset, node_to_focus, offset)
    }

}

function has_content(el) {
    if (!el) {  // Так иногда бывает
        return false;
    }

    if (
        el.textContent !== '' ||
        (el.innerHTML).includes('<img')
    ) {
        return true;
    }
    return false;
}

function remove_selected_contents() {
    const selection = document.getSelection();
    const range = selection.getRangeAt(0);
    range.deleteContents();
}

function all_kind_of_spaces_to_whitespaces(string) {
    let result = string;
    result = result.replaceAll(/\t/g, '    ');  // Табы заменяем на 4 пробела
    result = result.replaceAll('&nbsp;', ' ').replaceAll('&nbsp', ' ')
                   .replaceAll('&emsp;', ' ').replaceAll('&emsp', ' ')
                   .replaceAll('&ensp;', ' ').replaceAll('&ensp', ' ');
    return result;
}

function normalize_spaces(data) {
    const data_lines = data.split('\n');
    const result_lines = []
    for (const line of data_lines) {
        let cleaned_line = all_kind_of_spaces_to_whitespaces(line);
        let result_line = cleaned_line.trimStart();
        const spaces_to_prepend_num = cleaned_line.length - result_line.length;
        let spaces_to_prepend = '';
        while (spaces_to_prepend.length < spaces_to_prepend_num) {
            spaces_to_prepend += (spaces_to_prepend.length % 2) ? ' ' : '&';
        }
        spaces_to_prepend = spaces_to_prepend.replaceAll('&', '&nbsp;');
        result_line = spaces_to_prepend + result_line;
        result_lines.push(result_line);
    }
    const result = result_lines.join('<br>');
    return result;
}

// ИНИЦИАЛИЗАЦИЯ

Wysiwyg.init = function(contenteditable) {
    Wysiwyg.ensure_if_last_par_is_image_it_has_par_after(null, contenteditable);
}

Wysiwyg.add_event_listeners = function(el, data_obj) {
    el.addEventListener('keydown', function(e) {
        // Методы, содержащие e.preventDefault, для предотвращения ввода работают только в keydown (не input).
        Wysiwyg.prevent_input_in_image_block(e, el)
    });
    el.addEventListener('input', function(e) {
        // Методы, которым необходима работа после ввода работают только в input (не keydown)
        Wysiwyg.ensure_at_least_empty_par(e, el);
        Wysiwyg.ensure_if_last_par_is_image_it_has_par_after(e, el);
        
    });
    el.addEventListener('paste', async function(e) {
        await Wysiwyg.process_paste(e, this, true, true);

        // Курсор смещается — нужно пересмотреть предложение
        await Wysiwyg.consider_offer_to_load_images(e, el, data_obj);
    });

    // Предлагаем панель в максимуме случаев
    // Кроме keydown — потому что в нём мы ещё не знаем где окажется курсор
    el.addEventListener('keyup', async function(e) {
        await Wysiwyg.consider_offer_to_load_images(e, el, data_obj);
    });
    el.addEventListener('input', async function(e) {
        await Wysiwyg.consider_offer_to_load_images(e, el, data_obj);
    });
    el.addEventListener('click', async function(e) {
        await Wysiwyg.consider_offer_to_load_images(e, el, data_obj);
    });
    el.addEventListener('focus', async function(e) {
        await Wysiwyg.consider_offer_to_load_images(e, this, data_obj);
    });
    el.addEventListener('focusout', async function(e) {
        setTimeout(async () => {
            await Wysiwyg.remove_offer_to_load_images(e, this, data_obj);
        }, 300);
    });

    el.addEventListener('dragover', function(e) {
        // https://developer.mozilla.org/en-US/docs/Web/API/HTMLElement/dragover_event
        // https://developer.mozilla.org/en-US/docs/Web/API/HTMLElement/drop_event
        // https://stackoverflow.com/a/8415673/4117781
        e.preventDefault();  // Обязательно
    });

    el.addEventListener('drop', function(e) {
        e.preventDefault();
    });

    // Wysiwyg.handle_tab(e, this);  // Позже сделаем
    // Wysiwyg.prevent_default_formatting(e, this);  // Всё же разрешим базовое форматирование
}