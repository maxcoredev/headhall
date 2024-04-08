<script>
    import {onMount, onDestroy, browser, Fetch, Alarms, tick, Utils, Window, scrollStore, scrollingStore, getStore} from '/all.js';
    import Posts from '/src/posts/posts/Posts.svelte';

    export let data;

    let user = data.user;  // из-за user.svelte доступно
    let posts = data.posts;
    let posts_els = [];

    let first_post = posts && posts.length ? posts[0] : null;

    const POSTS_COUNT_TO_BE_ALWAYS_LOADED = 10;

    let show_prev_placeholder;
    let show_next_placeholder;
    if (posts && posts.length) {
        show_prev_placeholder = true;
        show_next_placeholder = true;
    } else {
        show_prev_placeholder = false;
        show_next_placeholder = false;
    }


    let observer;
    const options = {
        // root: null,  // Оставляем viewport, наверно
        // threshold: 0,  // Оставляем дефолт — [0] — т.е. именно при пересечении, а не полном захвате как в случае [1] | https://stackoverflow.com/a/49352038/4117781
        // rootMargin: '-1% 0% -99% 0%',  // Есть ещё рекомендация делать так, но вроде у нас ничего не летит
    };
    onMount(() => {
        observer = new IntersectionObserver(observe_callback, options);
    });

    scrollingStore.subscribe(async (is_scrolling) => {
        if (is_scrolling && $scrollStore.direction === 'TOP') {
            posts = [];
            await load({portion: 'BEGINNING'});
        }
    });

    // Начнём повествование.
    // Рассмотрим самый хардкорный кейс.
    //
    // Допустим —
    // На странице пользователя 100 постов.
    // Читатель остановился на 50-й.
    // И мы, такие упоротые — грузим всё по 1-й записи.
    //
    // С сервера нам возвращается следующая картина:
    //
    // ——— viewport ———
    // 50-й пост
    //
    // ——— /viewport ———

    // 0. Самое первое что вообще происходит —
    // — срабатывает директива use:post_created_action у самого первого отрисованного поста,
    // который в свою очередь вызывает этот `post_created`
    async function post_created(el, index) {
        await tick();  // Да — use:post_created_action не гарантирует что отрисовано всё. Элемент появился. Но может и не более.

        const is_first_post = Number(el.getAttribute('data-id')) === first_post.id;

        // 1. Вот к нам с сервера впервые прилетела запись (или несколько)
        if (is_first_post) {

            // При перезагрузке страницы по F5, браузер каждый раз пытается восстановить позицию скрола.
            // И, т.к. у нас чаще всего какой-то материал прилетает с сервера (SSR же), соответственно —
            // — возможность для какого-то браузерного скрола — есть.
            // Но — у нас лента сложная, качественно у браузера ничего не получится.

            // 2. Поэтому — берём init-скролл под свой контроль

            show_prev_placeholder = false;
            show_next_placeholder = false;

            // а) Если это была самая верхняя запись — отскролим наверх
            if (!posts[0].prev_id) {
                window.scrollTo({top: 0})

            // б) Если это была самая нижняя запись — отскролим вниз
            } else if (!posts.at(-1).next_id) {
                // Добавим верхний плейсхолдер. А то вдруг — скролить будет некуда.
                show_prev_placeholder = true;
                await tick();

                window.scrollTo({top: document.documentElement.scrollHeight})
            // в) Если это была центральная запись — отскролим там, чтобы захватить её верх.
            } else {

                // Добавим плейсхолдеры. А то вдруг — скролить будет некуда.
                show_prev_placeholder = true;
                show_next_placeholder = true;

                await tick();

                // Сделаем это самым простым доступным способом:
                el.scrollIntoView();

                // Но, поскольку теперь она в самом верху viewport — она перекрывается position-fixed-шапками.
                // Нужно отскролить ещё, чтобы пост вылез из под шапки:

                const css_root = getComputedStyle(document.documentElement);
                const header_height      = parseInt(css_root.getPropertyValue('--header-height'));
                const user_header_height = parseInt(css_root.getPropertyValue('--user-header-height'));
                const post_margin_bottom = parseInt(css_root.getPropertyValue('--post-margin-bottom'));

                const all_headers_height = header_height + user_header_height;
                const total_height_to_unscroll = all_headers_height + post_margin_bottom;
                const total_height_to_scroll = window.pageYOffset - total_height_to_unscroll;

                window.scrollTo({top: total_height_to_scroll});
            }
        }

        // 3. Далее — нужно загрузить следующие записи
        if (is_first_post) {

            // Сначала — верхние или нижние?
            // Тут нам нужно принять решение.
            // Поведение браузера.
            // Когда браузер загружает что-то «под» — скроллбар остаётся на месте.
            // Но когда «над» — скроллбар начинает бежать за контентом.
            // (И внашим случае отскроливая нас рано или поздно к самому первому материалу).
            // Т.к. загрузка вниз будет триггерить новые обзёрверы — мы не можем знать когда они остановяться.
            // А если загрузить сначала верхние — они будут все за областью видимости, и ничего триггерить не будут.
            // Поэтому — принимаем решение —
            // Сначала — загрузим верхние записи

            // 1. Грузим верхние записи. (Если они есть конечно).
            if (posts[0].prev_id) {

                // Тут есть нюанс.
                // Когда мы загрузим предыдущУЮ запись — на самом деле — она попадёт во viewport,
                // т.к. всегда есть какая-то нависающая fixed:position шапка и т.д.
                // И в этом случае — сработает observer и от неё, и внесёт свою частичку хаоса.
                // И тут нам нужно как-то предотвратить/заигнорировать/выключить observer того нового поста выше,
                // который находится во viewport, но перекрывается шапкой.

                // Более того — скорее всего, после отладки алгоритма — мы конечно не будем грузить по 1-му материалу.
                // Мы будем грузить несколько.
                // И что если под нависающими шапками окажется несколько материалов?
                // Тогда — вообще не будем добавлять к обзёрву новые верхние материалы,
                // которые попадают в поле зрение viewport.
                // Сделаем это через параметр `do_not_observe_new_if_visible: true`.

                await load({portion: 'BEFORE', index: 0, do_not_observe_new_if_visible: true});

                // И, т.к. мы не добавляем к обзёрву новые записи —
                // — что же тогда стриггерит загрузку более верхних материалов?
                // Вдруг так вышло — что они влезли все и со всех них снят обзёрвер?
                // В случае нашего дизайна — суммарной высоты шапок и минимальной высоты постов — это не вероятно.
                // Но дизайн может измениться.
                // И не хотелось бы из-за это возвращаться сюда снова.

                // Но, эту проблему решит наше крутое правило и его имлементация:
                // МЫ НЕ ХОТИМ, ЧТОБЫ КАКАЯ-ЛИБО ЗАГРУЗКА ШЛА КОГДА ПОЛЬЗОВАТЕЛЬ УПЁРСЯ В ГРАНИЦЫ.
                // МЫ ХОТИМ ЧТОБЫ ВСЕГДА БЫЛО ЗАРАНЕЕ ПРОГРУЖЕНО `POSTS_COUNT_TO_BE_ALWAYS_LOADED`.
                // И это то, что мы будем контролировать в `observe_callback`.
                // Поэтому, несмотря на то, что мы уже обработали загрузку материалов с этого первого поста —
                // Этот первый пост — мы тоже добавим в `observer.observe`.
                // И — обработать это правило, а также решить проблему выше —
                // это будет уже ответственностью `observe_callback`.
            }

            // 2. Загрузим нижние. (Если они есть конечно).
            // Индекс первого поста конечно — поменялся. Пересмотрим его пеперд загрузкой:
            let initial_post_index = posts.length - 1;
            if (posts[initial_post_index].next_id) {
                await load({portion: 'AFTER', index: initial_post_index});
            }
        }

        first_post = {};  // Больше не актуально, будет мешать

        // 4. Добавляем к `observer.observe` всё что есть
        // (Те верхние записи, которые попали в область видимсоти — просто не попадут в эту функцию ——
        // это на уровне `Posts.svelte: <div class="post" use:post_created_action ...>`).
        observer.observe(el);

        // 5. Если есть какой-либо плейсхолдер,
        // и как только первый элемент в направлении этого плейсхолдера оказывается за областью видимости —
        // — можем убрать плейсхолдер.
        await tick();  // на всякий
        const el_top = el.getBoundingClientRect().top;
        if (show_prev_placeholder && el_top < 0) {
            show_prev_placeholder = false;
        }
        if (show_next_placeholder && el_top > window.innerHeight) {
            show_next_placeholder = false;
        }
    }

    // 7. Настало время колбэков!)
    async function observe_callback(entries, observer) {
        // Каждый раз когда от элемента триггерится обзёрвер — нам доступны все обозреваемые элементы.

        // 1. Для начала — найдём все те, которые попали в поле зрения (viewport)
        let intersectings = entries.filter((entry) => entry.isIntersecting);

        if (!intersectings.length)
            return;

        // Возможно — у нас тут очередь из записей, которые хотят что-то прогрузить в одном и том же направлении.
        // 2. В таком случае — возьмём только верхнюю и только нижнюю записи
        let highest = intersectings[0];
        let lowest = intersectings.at(-1);

        // 3. А остальные — вообще сразу отключим.
        for (const entry of intersectings) {
            if (entry !== highest && entry !== lowest) {
                observer.unobserve(entry.target);
            }
        }

        // 4. Реализация НАШЕГО КРУТОГО ПРАВИЛА
        // Найдём самый верхний загруженный пост из всех и от него загрузим ещё верхних
        const highest_provoked_index = Number(highest.target.getAttribute('data-i'));
        const index_to_load_prev_from = get_index_to_load_from(highest_provoked_index, 'BEFORE');
        if (index_to_load_prev_from !== undefined) {
            await load({portion: 'BEFORE', index: index_to_load_prev_from});
        }
        observer.unobserve(highest.target);
        // Найдём самый нижний загруженный пост из всех и от него загрузим ещё нижних
        const lowest_provoked_index = Number(lowest.target.getAttribute('data-i'));
        const index_to_load_next_from = get_index_to_load_from(lowest_provoked_index, 'AFTER');
        if (index_to_load_next_from !== undefined) {
            await load({portion: 'AFTER', index: index_to_load_next_from});
        }
        observer.unobserve(lowest.target);

        // (Вполне возможно, что highest и lowest — одна и та же запись. Поэтому два отдельных `if`.).
    }

    function post_removed(el, index) {
        observer.unobserve(el);
    }

    onDestroy(() => {
        if (!browser)
            return;
        observer.disconnect();
    })

    const loading = {
        'BEFORE': false,
        'AFTER': false,
        'BEGINNING': false,
        'END': false,
        // 'MIDDLE': false,  // Его тут быть не может, это чисто серверная инициализирующая штука
    }

    async function load({portion='AFTER', index, do_not_observe_new_if_visible=false}={}) {
        if (loading[portion]) {
            return;
        } else {
            loading[portion] = true;
        }

        // Это нам понадобится в finish, чтобы понять на сколько нужно prevent браузер изменить положение scrollbar.
        await tick();  // Если что-то там рисовалось — дождёмся
        const height_before_load = document.documentElement.scrollHeight;
        const scroll_before_load = document.documentElement.scrollTop;

        let post = index !== undefined ? posts[index] : {};
        GET: try {
            const [r, data] = await Fetch.rdata(
                await fetch(`/api/user/posts/?username=${user.username}&provoked_id=${post.id || ''}&portion=${portion}`, {})
            );
            if (r.status === 422) {
                // Вроде тут нечего делать
            } else if (r.status === 200) {
                // Тут мы не можем быть уверены, что load_prev не загрузился раньше,
                // и соответственно — индексы не сбились. Поэтому ищем индекс заново.
                let new_index = 0;
                let new_posts = data;

                if (portion === 'AFTER' || portion === 'BEFORE') {
                    // А может они всё ещё совпадают и ничего искать не надо?
                    if (post.id === posts[index].id) {
                        new_index = index;
                    // Индекс действительно изменился
                    } else {
                        new_index = posts.findIndex(p => p.id === post.id);
                    }

                    if (portion === 'AFTER') {
                        new_index = new_index + 1;
                    }

                    if (portion === 'BEFORE') {
                        // Навесим параметр, который позволит в use: каждого поста на добавляться в обзёрвер.
                        let new_posts = data;
                        if (do_not_observe_new_if_visible) {
                            for (const new_post of new_posts) {
                                new_post.do_not_observe_if_visible = true;
                            }
                        }
                    }
                }

                posts = Utils.Array.extend(posts, new_posts, new_index);
                // (Вполне вероятно — data никакой и нет, вернётся пустой массив. Это не страшно.)

                // На этом моменте — браузер будет пытаться отскролить к материалам, которые мы только что загрузили.
                // Но мы этого не хотим в большинстве случаев.
                // Кроме одного — когда кто-то нажал на какую либо стрелочку (или шапку), которая триггерит прокрутку вверх.
                // Такие стрелочки/шапки мы реализовываем не через обычный `window.scrollTo`,
                // А через кастомный Window.scroll_to, который докладывает о своём состоянии в `scrollStore`.
                // И если происходит такой autoscroll (т.е. не пользовательский) — со своей стороны — отпускаем контроль.
                // Что будет делать при этом браузер — нам не важно. Window.scroll_to всё равно дотянет куда надо.

                // Итак,
                const is_autoscroll_in_progress = $scrollStore.is_scrolling;
                if (is_autoscroll_in_progress) {
                    break GET;
                }

                if (portion === 'BEFORE') {
                    // Если никакого autoscrollа нет, значит — scroll — браузерный.
                    // Напомним — он пытает докрутить до новых материалов сверху.
                    // Возвращаем скролл назад.
                    await tick();  // Подождём пока всё отрисуется, чтобы получить новые высоты достоверно.
                    const height_after_load = document.documentElement.scrollHeight;
                    const new_content_height = height_after_load - height_before_load;
                    window.scrollTo({top: scroll_before_load + new_content_height});
                }

            } else {Alarms.upset(data);}
        } catch (err) {console.error(err);} finally {
            loading[portion] = false;
        }
    }

    function get_index_to_load_from(provoked_index, portion='AFTER') {
        const sign = (portion === 'AFTER') ? +1 : -1;
        const further_id_field_name = (portion === 'AFTER') ? 'next_id' : 'prev_id';

        let index_to_load_from = undefined;
        const indexes = Utils.range(provoked_index, provoked_index + (POSTS_COUNT_TO_BE_ALWAYS_LOADED * sign));

        for (const index of indexes) {
            const further_index = index + (1 * sign);
            const further_post = posts?.[further_index];
            const post = posts[index];

            // Если у рассматриваемого поста (даже того, что стриггерил дозагрузку) нет `further_id_field_name`,
            // значит — грузить нечего. Сваливаем ИЗ ЦИКЛА.
            if (!post[further_id_field_name]) {
                break;

            // Если следующий пост уже есть, и у него ожидаемый id — сваливаем ИЗ ТЕКУЩЕЙ ИТЕРАЦИИ и продолжаем проверки.
            } else if (further_post && further_post.id === post[further_id_field_name]) {
                continue;

            // Вот теперь нам точно придётся что-то загрузить
            // Тут либо нет следующего поста, либо — следующий пост загружен ранее и он не тот, что нам нужен.
            // Грузим, и валим ИЗ ЦИКЛА.
            } else {
                index_to_load_from = index;
                break;
            }
        }

        return index_to_load_from;
    }
</script>

{#if show_prev_placeholder}
    <div style="height:100dvh"></div>
{/if}

<Posts bind:posts bind:posts_els {post_created} {post_removed} page_type="USER"/>

{#if show_next_placeholder}
    <div style="height:100dvh"></div>
{/if}
