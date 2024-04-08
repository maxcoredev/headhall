<script>
    import {
        MEDIA_API_URL,
        Loader, Icons, Utils, Idnk,
        onMount, onDestroy, tick, browser, Dropdowns,
        lethargyStore, performanceStore, Device
    } from '/all.js';
    import PinchZoom from 'pinch-zoom-js';

    let slider;  // html-тэг .SLIDESHOW_SLIDER
    
    let Slider = new function() {
        // Вся эта каша была сварена вот из этого топора, от которого совершенно ничего не осталось:
        // https://codepen.io/toddwebdev/pen/yExKoj (от него ничего не осталось)
        
        // Переменные, которые нам понадобятся в шаблонах, определяем через this.
        
        // А вот к этим мы вообще обращаемся всегда через Slider.x, чтобы триггерить обновление UI
        this.current_slide_index = null;
        this.offset_y = null;

        // Ниже мы тоже определяем переменные через this, но изначально только для того,
        // чтобы иметь возможность их легко пеереинициализировать.
        // Но, Slider.is_dragging и Slider.is_animating теперь используются в pinch-zoom
        // А по Slider.intention === 'CLOSE' мы увеличиваем z-index картинке
        // Поэтому — хорошо, что вынесли
        ;(() => {
            this.reset_dragging = () => {
                // Обязательно нужно пересечивать после каждого завершённого действия (кроме анимации):
                this.is_dragging = false;
                this.intention = [null, 'LEAF', 'CLOSE'][0];
                this.pixels_per_move = 0;
            }

            this.reset_animation = () => {
                // Обязательно нужно отменять анимацию при destroy,
                // иначе этот бесконечный `while` никогда не завершится
                this.is_animating = false;
            }
            
            this.reset_speed_coefs = () => {
                // Не смотря на то, что скорость у нас всегда зависит от расстояния,
                // На разных устройствах это ощущается по разному.
                // Дополняем «коэффициентом ширины экрана»

                const BASE_SIZE_COEF = 2000;
                const devicePixelRatio = window.devicePixelRatio || 1;
                this.WIDTH_COEF = Utils.round(slider.offsetWidth / devicePixelRatio / BASE_SIZE_COEF, 2);
                this.HEIGHT_COEF = Utils.round(slider.offsetHeight / devicePixelRatio / BASE_SIZE_COEF, 2);

                // На телефонах экран чаще вытянутый по вертикали, а на компах — по горизонтали.
                // Увеличиваем скорость по высоте там где высота больше ширины
                const PROPORTION_COEF = Utils.max_div_min_abs(slider.offsetWidth, slider.offsetHeight);
                this.HEIGHT_COEF = this.HEIGHT_COEF > this.WIDTH_COEF ? this.HEIGHT_COEF * PROPORTION_COEF : this.HEIGHT_COEF;

                // Листания
                this.SLIDE_LEAF_BOOST_COEF       = 24 * this.WIDTH_COEF;
                this.SLIDE_LEAF_BACK_BOOST_COEF  = 24 * this.WIDTH_COEF;
                this.SWIPE_LEAF_BOOST_COEF       = 18 * this.WIDTH_COEF;
                this.SWIPE_LEAF_BACK_BOOST_COEF  = 12 * this.WIDTH_COEF;

                // Закрывания
                this.SLIDE_CLOSE_BOOST_COEF      = 36 * this.HEIGHT_COEF;
                this.SLIDE_CLOSE_BACK_BOOST_COEF = 36 * this.HEIGHT_COEF;
                this.SWIPE_CLOSE_BOOST_COEF      = 6 * this.HEIGHT_COEF;
                this.SWIPE_CLOSE_BACK_BOOST_COEF = 6 * this.HEIGHT_COEF;  // Он на самом деле пока не нужен, т.к. при «обратном свайпе» мы ничего на место не возвращаем, а выкидываем, но просто в другую сторону

                // Чем больше BASE_SIZE_COEF —
                // тем тоньше мы можем управлять всеми остальными [SLIDE|SWIPE]_[LEAF|CLOSE][_BOOST]_COEF
                // Т.е. BASE_SIZE_COEF может быть любым. Но тогда нужно будет пересмотреть и прочие.
            }

            this.reset_pixels_per_move_coefs = () => {
                // ЗАДАЧА
                // Нужно найти наибольшее число пикселей, которое резко проходит палец/тачпад/мышка, когда мы ожидаем именно свайпинг.
                // Нужно именно наибольшее, чтобы не войти в конфликт с обычным слайдингом.

                // ПРОВОДИМ РУЧНОЕ ТЕСТИРОВАНИЕ
                // Если при определённом числе (начинаем с 10) мы считаем,
                // что свайп уже не вызывает дискомфорта — используем это число.

                // РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ:
                // Android в обычном режиме           : 1. Хотя и тут иногда бывает, что свайпа не происходит.
                // Android в энергосберегающем режиме : 2. Всё прекрасно.
                // iPhone в обычном режиме            : 2. Всё прекрасно.
                // iPhone в энергосберегающем режиме  : 2. Всё прекрасно.
                // Macbook на тачпаде                 : 4.
                // Macbook на мышке                   : 3. Хотя если долго мучаться — можно выжать и 2.

                // ТЕПЕРЬ — КАЗАЛОСЬ БЫ — ЗАДАЧА:
                // Опираясь на производительность — получить примерно такие же значения.
                // Но — не совсем так.
                // Потому что для свайпа мышкой и тачпадом — нужен меньший показатель даже на самом производительном компе.
                // Поэтому — сделаем это только для мобильных устройств.

                // НО!
                // Почему энергосберегающий iPhone распознаёт свайп лучше чем более производительный Android в обычном режиме?
                // Это можно объяснить только одним — лучшей чувствительностью экрана iPhone! (устройств Apple в целом наверн)

                // ПОЭТОМУ:
                let swipe_coef;
                if (IS_MOBILE_DEVICE) {
                    if (IS_MOBILE_ANDROID || $lethargyStore > 1.2) {
                        swipe_coef = 1;
                    } else if (IS_MOBILE_IOS) {
                        swipe_coef = 2;
                    } else {  // Сюда попадут виндофоны и прочее непопулярное
                        swipe_coef = 2;  // Cчитаем, что у них тоже чувствительные экраны
                    }
                } else {  // Ну и для компов
                    swipe_coef = 3;
                }
                this.PIXELS_PER_MOVE_TO_CONSIDER_SWIPE_LEAF = swipe_coef;
                this.PIXELS_PER_MOVE_TO_CONSIDER_SWIPE_CLOSE = swipe_coef;
            }
        })();

        // Переменные, которые нам и в шаблонах не нужны, и переинициализировать их не нужно

        let initial_document_scroll_top;

        let initial_scroll_on_mousedown;
        let initial_x_on_mousedown;
        let initial_y_on_mousedown;
        let current_x;
        let previous_x;
        let current_y;
        let previous_y;
        let dragged_distance;

        this.PART_OF_SCREEN_HEIGHT_TO_CLOSE_COEF = 4;

        const MIN_DISTANCE_TO_INTENT_LEAF = 6;
        const MIN_DISTANCE_TO_INTENT_CLOSE = 12;
        const STOP_SLIDING_ON_PERCENT_RICH = 90;
        const SLIDING_BOOST_COEF = 2;
        const CLOSING_BOOST_COEF = 1.5;
        
        // Говорят — человеческий глаз улавливает 30-60 кадров в секунду.
        // Мы будем исходить из того, что — 100. Для простоты алгоритма и инопланетян.
        // Поэтому — обновляем раз в 10 милисекунд.
        const ANIMATION_DELAY_MS = 10;

        // Но, т.к. ANIMATION_DELAY_MS именно задержка, между циклами,
        // а у нас есть ещё и код, который также требует времени на исполнение,
        // увеличиваем «шаг анимации» на те же 10, но — прибавим ещё 1, типа на код.
        // На самом деле это не очень нужно, но — укажем это явно.
        // Вспомним про это если решим взять анимацию под прям совсем жёсткий контроль.
        const ANIMATION_BOOST_MS = 11;

        const animate = async ({object, property, to, speed, is_swipe, callback, update}={}) => {
            if (this.is_animating)
                return;

            // По ходу происходит много всякого треша.
            // И очистим мы его — в одном месте — тут. В анимейте.
            const abs_speed = Math.abs(speed); // Вполне может прийти отрицательным;
            const lethargy = $lethargyStore || 1;  // Если не успелость проверить или что либо пошло не так.

            let swipe_boost;
            if (is_swipe && this.pixels_per_move) {
                swipe_boost = Math.max(Math.round(this.pixels_per_move / 10), 2) // Ещё ускорим в зависимости от резкости свайпа, но не более чем на 2
            } else {
                swipe_boost = 2;
            }

            // Итак,
            let pixels_per_frame = abs_speed * lethargy * swipe_boost * ANIMATION_BOOST_MS;
            pixels_per_frame = Math.max(pixels_per_frame, 1);  // Браузер не будет прибавлять к scrollLeft дробные значения меньше единицы (хотя position-top — будет)
            pixels_per_frame = Math.round(pixels_per_frame);   // А вот тепеь округлим

            const ensure_and_finish_animation_and_go_further = () => {
                object[property] = to;
                this.reset_animation();
                if (update) {
                    update();
                }
                if (callback) {
                    callback();
                }
            }

            // Отказываемся от казалось-бы хорошей идеи setInterval, т.к. он непредсказуем. Делаем while + delay
            // https://stackoverflow.com/questions/6951727/setinterval-not-working-properly-on-chrome

            this.is_animating = true;

            while (this.is_animating) {
                if (object[property] < to) {
                    object[property] += pixels_per_frame;
                    if (object[property] >= to) {
                        ensure_and_finish_animation_and_go_further();
                    }
                } else if (object[property] > to) {
                    object[property] -= pixels_per_frame;
                    if (object[property] <= to) {
                        ensure_and_finish_animation_and_go_further();
                    }
                } else {
                    ensure_and_finish_animation_and_go_further();
                }
                await Browser.delay(ANIMATION_DELAY_MS);
                if (update) {
                    update();
                }
                // console.log('ANIMATING', property, object[property], to)
            }
        }

        // Двигаемся по горизонтали

        const scroll_to_b = ({scroll_to, perform_leaf=false, is_swipe=false, callback}={}) => {
            // Всё, что нам тут остаётся — понять скорость и вызвать анимацию

            // Сколько крутить?
            const remaining_distance = Utils.max_sub_min(slider['scrollLeft'], scroll_to);
            
            // Если прокрутить 200, когда весь слайд это 1000, скорость медленная — 0.2
            // Если прокрутить 500, когда весь слайд это 1000, скорость средняя — 0.5
            // Если прокрутить 800, когда весь слайд это 1000, скорость высокая — 0.8
            let base_speed = remaining_distance / slider.offsetWidth;
            
            let boost;
            if (is_swipe && perform_leaf)   boost = this.SWIPE_LEAF_BOOST_COEF;
            if (is_swipe && !perform_leaf)  boost = this.SWIPE_LEAF_BACK_BOOST_COEF;
            if (!is_swipe && perform_leaf)  boost = this.SLIDE_LEAF_BOOST_COEF;
            if (!is_swipe && !perform_leaf) boost = this.SLIDE_LEAF_BACK_BOOST_COEF;
            
            const speed = base_speed * boost;

            animate({object: slider, property: 'scrollLeft', to: scroll_to, speed: speed, is_swipe: is_swipe, callback: callback});
        }

        const scroll_to_right = ({perform_leaf=false, is_swipe=false}={}) => {
            // Если мы уже правее некуда — валим отсюда
            if (perform_leaf && Slider.current_slide_index >= images.length - 1)
                return;

            const slider_width = slider.offsetWidth;
            const scroll_to = Math.trunc(slider.scrollLeft / slider_width) * slider_width + slider_width;

            if (perform_leaf) {
                scroll_to_b({scroll_to: scroll_to, perform_leaf: true, is_swipe: is_swipe, callback: () => {
                    Slider.current_slide_index = Math.min(Slider.current_slide_index + 1, images.length - 1);  // всё равно страхуемся
                }});
            } else {
                scroll_to_b({scroll_to: scroll_to, perform_leaf: false, is_swipe: is_swipe})
            }
        }

        const scroll_to_left = ({perform_leaf=false, is_swipe=false}={}) => {
            // Если мы уже левее некуда — валим отсюда
            if (perform_leaf && Slider.current_slide_index <= 0)
                return;

            const scroll_to = Math.trunc(slider.scrollLeft / slider.offsetWidth) * slider.offsetWidth;

            if (perform_leaf) {
                scroll_to_b({scroll_to: scroll_to, perform_leaf: true, is_swipe: is_swipe, callback: () => {
                    Slider.current_slide_index = Math.max(Slider.current_slide_index - 1, 0);  // всё равно страхуемся
                }});
            } else {
                scroll_to_b({scroll_to: scroll_to, perform_leaf: false, is_swipe: is_swipe});
            }
        }

        const slide_scroll_to_closest = () => {
            const is_less_than_a_half = Math.abs(dragged_distance) < slider.offsetWidth / 2;

            // Если листали вперёд/направо (dragged_distance ушёл в минус)
            if (dragged_distance < 0) {
                // Но пролистали совсем чуть-чуть
                if (is_less_than_a_half) {
                    scroll_to_left();  // Откатим налево
                } else {  // А если пролистали как-минимум половину
                    scroll_to_right({perform_leaf: true});  // Перелистнём направо
                }

            // Если листали обратно (dragged_distance ушёл в плюс)
            } else if (dragged_distance > 0) {
                // Но пролистали совсем чуть-чуть
                if (is_less_than_a_half) {
                    scroll_to_right();  // Откатим направо
                } else {  // А если пролистали как-минимум половину
                    scroll_to_left({perform_leaf: true});  // Перелистнём налево
                }
            }
        }

        // Двигаемся по вертикали

        const slide_nod_to_closest = () => {
            // Если протащили более трети высоты экрана — точно закрываем
            // Вроде как, именно с">=" лучше согласовывается с изменением opacity (но это не точно, возможно зависит от дроби и округления)
            if (Math.abs(Slider.offset_y) >= slider.offsetHeight / this.PART_OF_SCREEN_HEIGHT_TO_CLOSE_COEF) {

                // Убиваем mousedown/touchstart и pinch_zoom
                prepare_destroy();

                // Чем меньше нам остаётся до закрытия — тем выше должна быть скорость
                const base_speed_to_close = Math.abs(Slider.offset_y) / slider.offsetHeight;
                const speed = base_speed_to_close * this.SLIDE_CLOSE_BOOST_COEF;

                // Теперь нужно понять — выкинуть вверх, или вниз?
                let nod_to;
                if (Slider.offset_y < 0) {
                    nod_to = -slider.offsetHeight;
                } else {
                    nod_to = slider.offsetHeight;
                }

                animate({
                    object: Slider,
                    property: 'offset_y',
                    to: nod_to,
                    speed: speed,
                    callback: () => {
                        close();
                    },
                    update: () => {  // Чисто для svelte;
                        Slider.offset_y = Slider.offset_y;
                    }
                });

            // Если меньше
            } else {
                // Возвращаемся назад
                const base_speed_to_align_back = Math.abs(Slider.offset_y) / slider.offsetHeight;
                const speed = base_speed_to_align_back * this.SLIDE_CLOSE_BACK_BOOST_COEF;
                animate({
                    object: Slider,
                    property: 'offset_y',
                    to: 0,
                    speed: speed,
                    callback: () => {
                        Slider.offset_y = 0;
                    },
                    update: () => {
                        Slider.offset_y = Slider.offset_y;  // Чисто для svelte;
                    },
                });
            }
        }

        // Два основных действия пользователя:

        const dragging = (e) => {
            // Тут мы двигаем с зажатой кнопкой

            if (pinching_el)
                return;

            this.is_dragging = true;

            // Поймём общие параметры движения
            previous_x = current_x || e.pageX || e.touches[0].pageX;
            current_x = e.pageX || e.touches[0].pageX;
            previous_y = current_y || e.pageY || e.touches[0].pageY;
            current_y = e.pageY || e.touches[0].pageY;
            const x_distance = Utils.max_sub_min(initial_x_on_mousedown, current_x)
            const y_distance = Utils.max_sub_min(initial_y_on_mousedown, current_y)

            // Определим наше желание.
            // Для удобства запишем его в удобочитаемую переменную,
            // это нам понадобится когда мы отпустим мышку,
            // тогда мы будем знать — хотим ли мы свайпом перелистнуть или закрыть

            // Если мы уже определились — хотим ли мы листать или закрыть — то обратного пути нет. Нужно отпустить мышку
            if (!this.intention) {
                // Если ни по X и ни по Y мы не прошли достаточного расстояния
                if (x_distance <= MIN_DISTANCE_TO_INTENT_LEAF && y_distance <= MIN_DISTANCE_TO_INTENT_CLOSE) {
                    // Ничего не решаем
                } else if (x_distance > MIN_DISTANCE_TO_INTENT_LEAF) {
                    this.intention = 'LEAF'
                } else if (y_distance > MIN_DISTANCE_TO_INTENT_CLOSE) {
                    this.intention = 'CLOSE'
                }
            }

            // До тех пор пока мы не отпустили мышку — делаем лайтовое действие
            if (this.intention === 'LEAF') {
                leafing();
            } else if (this.intention === 'CLOSE') {
                closing();
            }
        }

        const leafing = () => {
            dragged_distance = (current_x - initial_x_on_mousedown) * SLIDING_BOOST_COEF;

            // Когда при листании упрёмся в 90% картинки — перестаём двигать. Пусть отпустит мышку. Это из телеги.
            if (Math.abs(dragged_distance) < slider.offsetWidth / 100 * STOP_SLIDING_ON_PERCENT_RICH) {
                slider.scrollLeft = initial_scroll_on_mousedown - dragged_distance;
            }
        }

        const closing = () => {
            dragged_distance = (current_y - initial_y_on_mousedown) * CLOSING_BOOST_COEF;

            // На основе этого параметра мы будет менять position-top, и менять opacity bg и превью
            Slider.offset_y = dragged_distance;
        }

        // Отпускаем мышку

        const perform_intention_on_mouse_up = () => {
            // Если хотели листнуть, и действительно листали, а не вернули мышку в исходное положение
            if (this.intention === 'LEAF' && slider.scrollLeft !== initial_scroll_on_mousedown) {
                // Сколько же мы продвигали по X?
                this.pixels_per_move = Utils.max_sub_min(current_x, previous_x)
                // console.log(this.pixels_per_move)
                // Тонкое место.
                // Пользователь мог двигать так быстро, что браузер не записывает его как плавное,
                // и фиксирует движение не как X + 1, а как X + 2, или 3, 4,
                // и вплоть до + 20 вроде можно, особенно если устройство старое и тормознутое.
                // Итак, если двигались быстро — свайпим.
                if (this.pixels_per_move >= this.PIXELS_PER_MOVE_TO_CONSIDER_SWIPE_LEAF) {
                    // Какой смысл что-то двигать если картинка всего одна? Не может быть таких желаний
                    if (images.length === 1)
                        return;
                    swipe_leaf();
                } else {
                    // Если двигались с маленькой скоростью,
                    // то, при отпускании — сначала решаем — листать или вернуть какртинку в исходное,
                    // в зависимости от того как далеко мы проскролили
                    slide_scroll_to_closest();
                }

            // Если хотели закрыть, и действительно закрывали, а не вернулись в исходное положение
            } else if (this.intention === 'CLOSE' && Slider.offset_y !== 0) {
                this.pixels_per_move = Utils.max_sub_min(current_y, previous_y)
                if (this.pixels_per_move > this.PIXELS_PER_MOVE_TO_CONSIDER_SWIPE_CLOSE) {
                    swipe_close();
                } else {
                    slide_nod_to_closest();
                }
            } else {
                // Тут мы остановили слайдер вторым пальцем.
                // У нас нет ни dragged_distance, ни intention.
                // Нужно просто докатить туда откуда начали.
                // Не лучшее решение, но — простое.
                slider.scrollLeft = Slider.current_slide_index * slider.offsetWidth;
            }
        }

        const swipe_leaf = () => {
            // Если мы тут — значит — зафиксировали резкое движение — точно нужно куда-то свайпнуть.
            
            // И тут интересное место.
            // Пользователь может — начать скролить в однУ сторону, и проскролить очень далеко,
            // а потом резко свайпнуть в противоположную сторону.
            // Именно из-за это кейса все усложнения.
            // Но по ходу всё будет понятно.

            // Куда тянем или свайпим по итогу?
            const last_direction = current_x > previous_x ? 'LEFT' : 'RIGHT';

            // Т.е. значит ведём мы пальцем влево, листая тем самым нормально направо/вперёд
            if (dragged_distance < 0) {
                // А потом так — хоп резко палец вправо, ожидая листания налево/назад
                if (last_direction === 'LEFT') {
                    // В этом случае — возвращаем его тогда на ту картинку с которой начали листать
                    // Но — с резкой анимацией свайпа
                    scroll_to_left({is_swipe: true});  // swipe_scroll
                } else {
                    // Если листал по-человечеси — перелистываем с анимацией свайпа
                    scroll_to_right({perform_leaf: true, is_swipe: true});  // swipe_scroll
                }
            } else if (dragged_distance > 0) {  // Всё то же самое только наоборот
                if (last_direction === 'RIGHT') {
                    scroll_to_right({is_swipe: true});  // swipe_scroll
                } else {
                    scroll_to_left({perform_leaf: true, is_swipe: true});  // swipe_scroll
                }
            }
        }

        const swipe_close = () => {

            // Куда тянем или свайпим по итогу?
            const last_direction = current_y > previous_y ? 'BOTTOM' : 'TOP';

            let remaining_distance;
            let slide_to;
            let speed;
            let coef;

            if (dragged_distance < 0) {
                if (last_direction === 'BOTTOM') {
                    // Выбрасываем вниз
                    remaining_distance = slider.offsetHeight - Slider.offset_y
                    slide_to = slider.offsetHeight;
                    coef = this.SWIPE_CLOSE_BACK_BOOST_COEF;
                } else {
                    // Выбрасываем вверх
                    coef = this.SWIPE_CLOSE_BOOST_COEF;
                    remaining_distance = slider.offsetHeight + Slider.offset_y
                    slide_to = -slider.offsetHeight;
                }
            } else {
                if (last_direction === 'TOP') {
                    // Выбрасываем вверх
                    coef = this.SWIPE_CLOSE_BOOST_COEF;
                    remaining_distance = slider.offsetHeight + Slider.offset_y
                    slide_to = -slider.offsetHeight;
                } else {
                    // Выбрасываем вниз
                    remaining_distance = slider.offsetHeight - Slider.offset_y
                    slide_to = slider.offsetHeight;
                    coef = this.SWIPE_CLOSE_BACK_BOOST_COEF;
                }
            }

            speed = slider.offsetHeight / remaining_distance * coef;  // чем дальше выбрасывать тем быстрее бросок

            // Убиваем mousedown/touchstart и pinch_zoom
            prepare_destroy();

            // Выбрасываем
            animate({
                object: Slider,
                property: 'offset_y',
                to: slide_to,
                speed: speed,
                is_swipe: true,
                callback: () => {
                    close();
                }, update: () => {
                    Slider.offset_y = Slider.offset_y;  // Чисто для svelte;
                },
            });
        }

        const prepare_destroy = () => {
            // На этом моменте, мы уже приняли решение о закрытии.
            // Поэтому — перестаём слушать любые события.
            // Иначе, если анимация медленная — мы сможем ещё что-то подёргать
            remove_primary_events();
            disable_pinch_zoom(this.current_slide_index);
        }

        // Стрелочки/превьюшки и финал

        this.leaf_on_click = (index) => {
            // Событие происходит когда мы кликаем по стрелочками или превьюшкам.

            if (this.is_animating || this.is_dragging)
                return;

            if (pinching_el)
                reset_pinch_zoom();

            const scroll_to = index * slider.offsetWidth;
            scroll_to_b({
                scroll_to: scroll_to,
                is_swipe: true,
                perform_leaf: true,
                callback: () => {
                    Slider.current_slide_index = index;
                }
            });
        }

        const complete_dragging_on_click = () => {
            // Это самое старшее событие.
            // Вызывается после всего — после всех драгов, свайпов, кликов по стрелочкам.
            // Нужно просто для того, чтобы сказать, что мы больше ничего не this.is_dragging.
            // Таким образом, если мы начали с драгинка, клик по стрелочке — не будет отрабатывать.
            // Потому что стрелочки знают, что this.is_dragging = true.

            // Итак, завершаем всё, что должно быть завершено, после того, как мы отпустили мышку, и перелистнули.
            // На этом моменте всё ещё может быть анимация, после которой ещё что-то сбросится (положение по y в случае закрытия).
            // Но, это всё дело анимации.
            this.reset_dragging();
            remove_secondary_events();
        }

        // Инициализация, события и разрушение

        this.resize = async () => {
            this.reset_speed_coefs();  // Ширина экрана изменилась — нужно пересчитать коэффициэнты
            this.set_scroll_left_based_on_current_slide_index();
        }

        this.init = () => {
            // Чуть позже мы навесим на весь документ position:fixed, чтобы запретить ненужные браузерные действия
            // Запомним положения скрола, приеним его как CCC position-top, позже вернём всё на место
            initial_document_scroll_top = document.documentElement.scrollTop;
            document.body.style.top = initial_document_scroll_top !== 0 ? `-${initial_document_scroll_top}px` : '0';

            // Запрещаем все ненужные браузерные действия средствами CSS
            document.documentElement.classList.add('is_scroll_disabled');
            document.documentElement.classList.add('is_user_select_none');
            document.documentElement.classList.add('is_overscroll_disabled');

            // Запрещаем все ненужные браузерные действия средствами JS
            listen_global_events();

            // Только тут в init инициализация slider-а может быть гарантирована
            // Считаем коэффициэнты скорости
            this.reset_speed_coefs();
            
            // Если мы открыли слайдшоу, нажав не на первую картинку — скроли до той, до на которую нажали
            // И запишем индекс той, на которую нажали
            Slider.current_slide_index = initial_image_index || 0;
            this.set_scroll_left_based_on_current_slide_index();

            // Уходим слушать первичные события
            listen_primary_events();

            // Измеряем скорость
            Device.measure_performance(() => {
                this.reset_pixels_per_move_coefs();
            });
        }

        this.set_scroll_left_based_on_current_slide_index = (e) => {
            slider.scrollLeft = Slider.current_slide_index * slider.offsetWidth;
        }

        const listen_global_events = (e) => {
            // Пытаемся запретить перелистывание истории браузера когда открыт слайдшоу
            // https://stackoverflow.com/a/48673566/4117781
            // slideshow_el.addEventListener('touchstart', Browser.preventDefault);  // И это действительно работает, но блокирует все click https://stackoverflow.com/a/58464663/4117781
            slideshow_el.addEventListener('touchmove' , Browser.preventDefault);
        }
        
        const remove_global_events = (e) => {
            // Пытаемся запретить перелистывание истории браузера.
            // Работает только если навесить на какой-то элемент (не body, не html)
            // Так как на слайдере уже дофига событий — вешаем на slideshow
            // slideshow_el.removeEventListener('touchstart', Browser.preventDefault);
            slideshow_el.removeEventListener('touchmove' , Browser.preventDefault);
        }
        
        const listen_primary_events = (e) => {
            if (!IS_MOBILE_DEVICE) {
                slider.addEventListener('mousedown', listen_secondary_events);
            } else {
                slider.addEventListener('touchstart', listen_secondary_events);
            }
        }
        
        const remove_primary_events = (e) => {
            if (!IS_MOBILE_DEVICE) {
                slider.removeEventListener('mousedown', listen_secondary_events);
            } else {
                slider.removeEventListener('touchstart', listen_secondary_events);
            }
        }
        
        const listen_secondary_events = (e) => {
            
            if (pinching_el)
                return;

            // Если оно медленно докатывается — а мы опять нажали, т.е. — поймали — останавливаем анимацию.
            // Вот когда отпустим мышку — разберёмся что, куда и как.
            this.is_animating = false;

            // Не будем каждый раз при перелистываниях перезаписывать — сколько мы в итоге сейчас отскролили
            // Будем смотреть это тут, каждый раз при нажатии мышки
            initial_scroll_on_mousedown = slider.scrollLeft;
            
            // Ну и зафиксируем координаты тоже тут, тут есть e
            initial_x_on_mousedown = e.pageX || e.touches[0].pageX;
            initial_y_on_mousedown = e.pageY || e.touches[0].pageY;

            // Слушаем вторичные события
            if (!IS_MOBILE_DEVICE) {
                slider.addEventListener('mousemove', dragging);
                slider.addEventListener('mouseup', perform_intention_on_mouse_up);
                slider.addEventListener('contextmenu', process_unexpected_events);
                slider.addEventListener('mouseleave', process_unexpected_events);
            } else {
                slider.addEventListener('touchmove', dragging);
                slider.addEventListener('touchend', perform_intention_on_touch_end);
            }
            slider.addEventListener('click', complete_dragging_on_click);
        }

        const remove_secondary_events = () => {
            if (!IS_MOBILE_DEVICE) {
                slider.removeEventListener('mousemove', dragging);
                slider.removeEventListener('mouseup', perform_intention_on_mouse_up);
                slider.removeEventListener('contextmenu', process_unexpected_events);
                slider.removeEventListener('mouseleave', process_unexpected_events);
            } else {
                slider.removeEventListener('touchmove', dragging);
                slider.removeEventListener('touchend', perform_intention_on_touch_end);
            }
            slider.removeEventListener('click', complete_dragging_on_click);
        }

        const perform_intention_on_touch_end = (e) => {

            // Ничем не отличается от perform_intention_on_mouse_up().
            // Поэтому — вызовем его.
            perform_intention_on_mouse_up();
            
            // Что если мы вышли за пределы экрана?
            // Тогда самое старшее событие click, которое должно всё обнулить — не вызовется.
            // Но всё равно вызовется touchend.
            // Поэтому — всё нормально.
            complete_dragging_on_click();
        }

        const process_unexpected_events = () => {
            // Просто завершаем, будто просто отпустили.
            // Но, по логике — здесь может оказаться что-то ещё.
            // Поэтому — проксируем.
            perform_intention_on_touch_end();
        }

        this.destroy = () => {
            document.documentElement.classList.remove('is_scroll_disabled');
            document.documentElement.classList.remove('is_user_select_none');
            document.documentElement.classList.remove('is_overscroll_disabled');

            // Возвращаем боди-скролл на место
            document.body.style.top = '0';
            document.documentElement.scrollTo(0, initial_document_scroll_top);

            // Единственная переменная которую нужно убить это is_animating
            // Иначе этот бесконечный `while` никогда не завершится
            this.reset_animation()

            // Все остальные переменные, а также события элементов умрут сами, так как при закрытии Svelte вырежет их из DOM

            // Но, глобальные события всё же нужно убрать явно
            remove_global_events();
        }

    }

    // Самый верхний элемент.
    // Навесим потом на него внутри Slider-а события,
    // блокирующие некоторые дефолтные действия браузера
    let slideshow_el;
    
    onMount(async () => {
        // await tick(); Может стоит на всякий случай?
        Slider.init();
    })

    onDestroy(() => {
        Slider.destroy();
    })
    
    // Принимаем переменные
    export let initial_image_index;
    export let type = [null, 'images', 'avatart'][0];
    export let file_names = []  // ['image-name-1.jpg', 'image-name-2.jpg', ...]
    export let state = {shown: false};
    export let is_author = false;
    export let delete_foo = async () => {};

    // Скопируем file_names, чтобы не конфликтовать при обратных коллбэках (важно)
    let images = [...file_names]

    // Создаём нечто более серьёзное, чем массив строк
    let items = []
    for (const image of images) {
        items.push({
            el: null,
            name: image,
            is_appeared: false,
            is_broken: false,
        })
    }

    // Закрываем, просто убивая переменную.
    // Делается это через объект из-за особенностей работы Svelte.
    // Вся остальная работа по закрытию отработает в onDestroy.
    function close() {
        state.shown = false;
    }
    
    // Когда картинка загрузилась — убираем лоадеры, навешиваем pinch-zoom
    async function img_appeared(node, index) {
        try {
            await node.decode();
            items[index].is_appeared = true;
        } catch (err) {
            if (err instanceof DOMException) {
                items[index].is_broken = true;
            }
        }
        items=items;

        if (!IS_MOBILE_DEVICE)
            return;

        await tick(); // Обязательно
        const img = items[index].el.querySelector('img');
        items[index].pinch_zoom = await init_pinch_zoom(img);
    }

    async function delete_image() {
        const file_name = items[Slider.current_slide_index].name;
        await delete_foo(file_name, async () => {
            items = items.filter((v) => v.name !== file_name);
            await tick();  // обязательно
            images = images.filter((v) => v !== file_name);

            // Меняем индекс
            if (!images.length) {
                close();
            } else {
                if (Slider.current_slide_index === images.length) {
                    Slider.current_slide_index = Math.max(images.length - 1, 0);
                }
                Slider.set_scroll_left_based_on_current_slide_index();
            }
        });
    }
    
    let pinching_el;
    let is_pinching;  // Вот прям прям сейчас тащим, чтобы увеличить картинке z-index

    // Есть кейс, когда нам нужно дождаться анимации от дабл-тапа.
    // И делаем мы это по setTimeout.
    // Подождать время анимации — не хватает.
    // Не хватает и прибавить несколько милисекунд.
    // На моём компе хватает 10-и.
    // На всякий лучай — подождём ещё 100.
    const PZ_ANIMATION_DURATION = 300;
    const PZ_WAIT_FOR_ANIMATION_END_MS = PZ_ANIMATION_DURATION + 100;

    async function init_pinch_zoom(img) {
        // https://github.com/manuelstofer/pinchzoom

        // ВЫБРАНА СЛЕДУЮЩАЯ ЛОГИКА:
        // Мы можем запинчить-зазумить — и оно так и останется. Пускай. Может хотят сделать принт-скрин.
        // В этот момент, Slider.drag выключиться (if is_pinching return;).
        // Чтобы снова включить Slider — нужно либо — дабл-тап и тем самым отзумить,
        // Либо — нажать на одну из стрелочек или превьюшек. Там произойдёт reset_pinch_zoom().

        // О ИВЕНТАХ ПЛАГИНА
        // 1. onZoomStart — надёжное событие для начала всех действий
        // 2. onDragEnd и onZoomEnd — эти события конфликтуют между собой в зависимоти от того как мы двигаем пальцами.
        // Они оба используются для определения, что пользователь вернул картинку в исходное состояние.
        // 3. onDoubleTap — тоже используются для определения, что пользователь вернул картинку в исходное состояние.
        // Но, он выбрасывается прежде, чем прошла анимация. Поэтому — приходится ждать её через setTimeout.
        // 4. Есть кейс, когда мы пинчим, и пальцы уходят за предел экрана.
        // Конечно плагин это не обрабатывает.
        // Для этого навешиваем своё событие `touchend`.

        // РАСКОВЫРЕНЫ НЕДОСТАЮЩИЕ ВНУТРЕННИЕ МЕТОДЫ
        // В плагине не задокументирован ни один метод.
        // Однако ресетить всё это как-то нужно.
        // Вот что было найдено полезого:
        // object.resetOffset();  // Выровнять по центру — отличный метод, используем.
        // object.zoomOutAnimation();  // Вернуть в исходное — отличный метод, используем.
        // object.sanitizeOffsetAnimation(); // Выровнять по ближайшему краю после всех манипуляций — не используем.

        // ТЕХНИЧЕСКАЯ ЛОГИКА
        // 1. Начинам весь движ с onZoomStart.
        // Однако, если мы прежде начали что-то тянуть в Slider-e, или там уже что-то анимируется — валим.
        // Для сваливания — object.disable(). Он как вместо e.stopPropogation.
        // 2. Если же мы pinch-zoom-им, Slider.drag выключиться (if is_pinching return;).
        // 3. Как закончили зумить/драгать/даблтапить — проверяем — если мы вернулись в исходную —
        // снимаем ограничения со Slider-a.
        // 4. Так как мы обрабатываем кейс, когда мы пинч-зумили и ушли за экран телефона —
        // у нас получается всегда есть наинадёжнейшее событие `touchend`.
        // Его же мы и используем для выравнивания картинки после любых манипуляций.
        // 5. Мы конечно блокируем Slider, но, кликанье по срелочкам или превьюшкам разблокирует Slider,
        // и вернёт картинку в исходную (`reset_pinch_zoom()`).

        let pinch_zoom = new PinchZoom(img, {
            draggableUnzoomed: false,  // Выключаем возможность подвигать картинку внутри почему-то растянутого враппера
            minZoom: 1, // Запрещаем уменьшать картинку
            maxZoom: 4, // 4 это дефолт, но укажем явно
            tapZoomFactor: 2,  // 2 это дефолт, но укажем явно
            animationDuration: PZ_ANIMATION_DURATION,  // 300 это дефолт
            onZoomStart: function(object, e) {
                if (Slider.is_dragging || Slider.is_animating) {
                    object.disable();
                } else {
                    object.enable();
                    pinching_el = object;
                }
            },
            onDragEnd: function(object, e) {
                clean_pinching_el(object);
            },
            onZoomEnd: function(object, e) {
                clean_pinching_el(object);
            },
            onDoubleTap: function(object, e) {
                setTimeout(() => {
                    clean_pinching_el(object);
                }, PZ_WAIT_FOR_ANIMATION_END_MS)
            },
        });

        img.addEventListener('touchend', function(e) {
            is_pinching = false;
            if (!pinching_el)
                return;
            if (e.pageX <= 0 || e.pageY <= 0) {  // Если touchend выбросился когда упёрлись пальцами в экран (значения могут уходить в минус)
                pinching_el.resetOffset();
            }
        });

        return pinch_zoom;
    }

    function disable_pinch_zoom(index) {
        if (!IS_MOBILE_DEVICE)
            return;
        items[index].pinch_zoom.disable();
    }

    function clean_pinching_el(object) {
        if (object.zoomFactor === 1) {
            pinching_el = null;
        }
    }

    function reset_pinch_zoom() {
        if (!pinching_el)
            return;
        // Уменьшая картинку
        pinching_el.zoomOutAnimation();
        setTimeout(() => {
            pinching_el.resetOffset();
        }, PZ_WAIT_FOR_ANIMATION_END_MS)
        pinching_el = null;
        is_pinching = false;
    }

    // Когда пытаем закрыть свайпом картинку — меняем opacity всем остальным элементам.
    // Прям в шаблоне. Переменная сложная, вынесем её отдельно.
    $: opacity = function(base) {
        if (!Slider.offset_y)
            return base;
        const part_of_screen_to_close = (slider.offsetHeight / Slider.PART_OF_SCREEN_HEIGHT_TO_CLOSE_COEF);
        const result = Math.max(base - (Math.abs(Slider.offset_y) / part_of_screen_to_close).toFixed(3), 0)
        return result;
    }

    // Сваливаем отсюда по нажатию на esc
    function close_on_escape(e) {
        if (e.key === 'Escape') {
            close();
        }
    }

    onMount(() => {
        if (IS_MOBILE_DEVICE)
            return;
        window.addEventListener('keydown', close_on_escape)
    })

    onDestroy(() => {
        if (!browser)
            return;
        if (IS_MOBILE_DEVICE)
            return;
        window.removeEventListener('keydown', close_on_escape)
    })

    // Контролируем click-outside like a pro
    let mousedown_el;
    let is_mousemoved;
    let _hovered;
</script>

<svelte:window on:resize={() => Slider.resize()}/>

<div class="SLIDESHOW"
    bind:this={slideshow_el}
    class:_ONEIMAGE={images.length === 1}
    style="background:rgba(0,0,0,{opacity(0.8)})"
    on:mousedown={(e) => {
        if (IS_MOBILE_DEVICE)
            return;
        mousedown_el = e.target;
    }}
    on:mousemove={(e) => {
        if (mousedown_el) {
            is_mousemoved = true;
        }
    }}
    on:mouseup={function (e) {
        if (IS_MOBILE_DEVICE)
            return;
        if (
            !is_mousemoved &&
            !mousedown_el.closest('[data-prevent-click-outside]') &&
            !e.target.closest('[data-prevent-click-outside]') &&
            !$Dropdowns.avatar_menu.active
        ) {
            close();
        }
        mousedown_el = null;
        is_mousemoved = false;
    }}
    on:mouseover={(e) => {
        _hovered = !e.target.closest('[data-prevent-click-outside]');
    }}
>
    <div class="SLIDESHOW_WINDOW">
        <div class="SLIDESHOW_HEADER" style="opacity:{opacity(1)}">
            {#if is_author}
                <div data-prevent-click-outside bind:this={$Dropdowns.avatar_menu.el} class="DROPDOWN ABSOLUTE _TOPLEFT">
                    <a data-prevent-click-outside tabindex="0" class="BUTTON _OUTSIDE _HIGHLIGHTLESS" on:click="{() => {
                        Dropdowns.toggle('avatar_menu');
                    }}" class:_CURRENT={$Dropdowns.avatar_menu.active}>
                        {@html Icons.menu({size: 36, attrs: 'data-prevent-click-outside'})}
                    </a>
                    {#if $Dropdowns.avatar_menu.active}
                        <div data-prevent-click-outside class="DROPDOWN_WINDOW _MENU _NOWRAP" style="top:100%;">
                            <a data-prevent-click-outside tabindex="0" class="DROPDOWN_ITEM _RED _ICON" on:click|preventDefault={async () => {
                                await delete_image();
                            }}>
                                {@html Icons.trash({size:24})}
                                Удалить
                            </a>
                        </div>
                    {/if}
                </div>
            {/if}
            <a tabindex="0" data-prevent-click-outside class="BUTTON _OUTSIDE _HIGHLIGHTLESS ABSOLUTE _TOPRIGHT" class:_HOVER={_hovered} on:click={close}>
                {@html Icons.x({size:42})}
            </a>
        </div>
        <div class="SLIDESHOW_SLIDER" id="slider" bind:this={slider}>
            {#each items as item, index (item.name)}
                <div class="SLIDESHOW_SLIDE" class:_BROKEN={item.is_broken}>
                    <div
                        bind:this={item.el}
                        class="SLIDESHOW_ITEM"
                        class:_BROKEN={item.is_broken}
                        class:_CLOSING_OR_PINCHING={Slider.intention === 'CLOSE' || is_pinching}
                        style="top:{Slider.offset_y}px"
                    >
                        {#if [index - 1, index, index + 1].includes(Slider.current_slide_index) || item.is_appeared || item.is_broken}
                            <img class="SLIDESHOW_IMG" data-prevent-click-outside
                                 class:IS_APPEARED={item.is_appeared || item.is_broken}
                                 class:_BROKEN={item.is_broken}
                                 use:img_appeared={index}
                                 src={`${MEDIA_API_URL}/${type}/${item.name}`}
                                 draggable="false"
                            >
                            {#if !item.is_appeared && !item.is_broken}
                                <Loader/>
                            {:else if item.is_appeared || item.is_broken}
                                {#if index < images.length - 1}
                                    <div class="SLIDESHOW_TO_NEXT SMOOTH" data-prevent-click-outside style="opacity:{Slider.offset_y ? 0 : 1}"
                                         on:click={() => Slider.leaf_on_click(Math.min(index + 1, images.length - 1))}
                                    ></div>
                                {/if}
                                {#if index !== 0}
                                    <div class="SLIDESHOW_TO_PREV SMOOTH" data-prevent-click-outside style="opacity:{Slider.offset_y ? 0 : 1}"
                                         on:click={() => Slider.leaf_on_click(Math.max(index - 1, 0))}
                                    ></div>
                                {/if}
                            {/if}
                        {:else}
                            <Loader/>
                        {/if}
                    </div><!-- Технология древних
                    --><span class="VERTICAL_ALIGN_MIDDLE_HACK"><!-- Ещё одна технология древних --></span>
                </div>
            {/each}
        </div>
        {#if images.length > 1}
            <div class="SLIDESHOW_THUMBS_WRAPPER" style="opacity:{opacity(1)}">
                <div class="SLIDESHOW_THUMBS" data-prevent-click-outside>
                    {#each images as image, index (image)}
                        <span data-prevent-click-outside
                              class="SLIDESHOW_THUMB SMOOTH _BROKEN"
                              class:_CURRENT={index === Slider.current_slide_index}
                              on:click={() => Slider.leaf_on_click(index)}
                        >
                            <img data-prevent-click-outside
                                 class="SLIDESHOW_THUMB_IMG SMOOTH"
                                 draggable="false"
                                 on:load={(e) => {e.target.parentElement.classList.remove('_BROKEN')}}
                                 src={`${MEDIA_API_URL}/${type}/${image}?mins=240`}
                            >
                        </span>
                    {/each}
                </div>
            </div>
        {/if}
    </div>
</div>
