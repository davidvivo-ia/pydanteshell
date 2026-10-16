# Dante's Hell — *Disciplinati*

### *Palle, palle, palle!* — una commedia per lemming

> *«Per me si va ne la città dolente…»*
> Y por ahí van, en fila, sin mirar, con el látigo en la mano: cien almas blancas con una cruz roja al pecho, convencidas de que treinta y tres días y medio de penitencia bastan para cruzar el Infierno, subir el Purgatorio y llegar al Cielo.
> No bastan. Para eso estás tú.

Un juego de puzles y rescate en la tradición de *Lemmings* (DMA Design, 1991): una horda que camina sola hacia la muerte y un jugador que solo puede asignar oficios para salvarla. La horda es una secta de flagelantes de 1348; el mapa, la *Divina Comedia*; las pausas, los diez narradores del *Decamerón*; la luz, la de Caravaggio; el poder, las *palle* del escudo de los Médici.

**Todo el juego es un único fichero, [`pydanteshell.py`](pydanteshell.py)**: unas 8.000 líneas de Python sin un solo recurso externo. El pixel art, la iluminación, la música, la voz que recita en italiano y los 101 niveles se generan por código al arrancar.

---

## Índice

1. [Arrancar en un minuto](#1-arrancar-en-un-minuto)
2. [El juego hoy, en cifras](#2-el-juego-hoy-en-cifras)
3. [Cómo se juega](#3-cómo-se-juega)
4. [Los nueve oficios](#4-los-nueve-oficios)
5. [Las palle, el Peso y la Moria](#5-las-palle-el-peso-y-la-moria)
6. [La Commedia: 101 niveles](#6-la-commedia-101-niveles)
7. [Las Giornate del Decamerón](#7-las-giornate-del-decamerón)
8. [Finales](#8-finales)
9. [Modos de juego](#9-modos-de-juego)
10. [Controles](#10-controles)
11. [Opciones y accesibilidad](#11-opciones-y-accesibilidad)
12. [Un juego de 2026: la superpensada](#12-un-juego-de-2026-la-superpensada)
13. [Gráficos y sonido](#13-gráficos-y-sonido)
14. [Arquitectura del código](#14-arquitectura-del-código)
15. [Pruebas y calibración](#15-pruebas-y-calibración)
16. [Formato de nivel (JSON)](#16-formato-de-nivel-json)
17. [Historia, tesis y licencias](#17-historia-tesis-y-licencias)
18. [Licencia](#18-licencia)

---

## 1. Arrancar en un minuto

Requisitos: Python 3.12 o superior, `pygame-ce` 2.5 o superior y `numpy` 2.0 o superior.

```bash
# con uv (lee las dependencias de la cabecera del propio fichero)
uv run pydanteshell.py

# o con pip
pip install pygame-ce numpy
python pydanteshell.py
```

Órdenes útiles:

```bash
python pydanteshell.py --level 33          # ir directo al Cocito
python pydanteshell.py --all               # desbloquear la Commedia entera
python pydanteshell.py --demo 34           # ver la solución de Lucifer
python pydanteshell.py --daily             # el Giudizio del giorno
python pydanteshell.py --endless           # modo Infinito
python pydanteshell.py --export-levels niveles/   # los 101 niveles en JSON
python pydanteshell.py --custom mi_nivel.json     # jugar un nivel propio
python pydanteshell.py --selftest          # 152 comprobaciones sin ventana
python pydanteshell.py --lowfx --scale 2   # equipos modestos
```

La partida se guarda en `~/.pydanteshell.json` (progreso, récords, logros, opciones y el estado de la Compagnia entre niveles).

---

## 2. El juego hoy, en cifras

| | |
|---|---|
| Niveles | **101**: Proemio, 34 del Inferno, 33 del Purgatorio y 33 del Paraíso, como los cantos de Dante |
| Almas por nivel | **100** disciplinati, más el Maestro Lapo (si vive) y el niño del Proemio |
| Oficios | **9**, todos **infinitos** |
| Palle | 6 tipos (5 rojas y la azul del lirio), en escudos de 8, 7 y 6 huecos |
| Guardianes | 18: Caronte, Minos, Cerbero, Pluto, Flegias, las Furias, los centauros, las harpías, Anteo, la lonza, el león, la loba, Catón, el Ángel portero, san Pedro, Santiago, san Juan y los excomulgados |
| Ambientes | 16 temas visuales, con fondos pintados por capas y partículas propias |
| Modificadores | 27 reglas de lugar (viento, noche, humo, ojos cosidos, hielo, gravedad invertida, serpientes…) |
| Modos | Campaña, Giudizio del giorno, Infinito, nivel propio en JSON, demos y repeticiones |
| Logros | 18, y estrellas (★ a ★★★) en cada nivel |
| Subtítulos | Español, inglés e italiano moderno (74 mensajes traducidos) |
| Voz | Síntesis por formantes que recita en italiano cada mensaje |
| Pruebas | 152 comprobaciones automáticas, entre ellas los 101 niveles resueltos con su solución de referencia |

---

## 3. Cómo se juega

Los *disciplinati* salen de una **pila bautismal** y caminan en línea recta. Si chocan con una pared se dan la vuelta; si caen desde más de 60 píxeles (ocho bloques) mueren; si tocan un peligro, también. **Tú no los mueves: les asignas oficios.** Cada nivel exige salvar un mínimo de almas antes de que se agoten los **33 días y medio** que el Maestro prometió.

Sobre esa base heredada de Lemmings se apoyan cinco ideas propias:

- **El contrapasso como mecánica.** Cada peligro es la forma de un vicio vuelta contra la horda: los avaros empujan peñas, los iracundos te hunden en el fango, los adivinos caminan mirando atrás, los hipócritas trabajan a media velocidad bajo capas de plomo.
- **El poder pesa.** Las palle dan poderes enormes, pero cada una que gastas añade **Peso**. En el Infierno no se nota; en el Purgatorio frena la subida; en el Primum Mobile, quien llega con Peso no asciende.
- **La peste está dentro de la horda.** La **Moria** se contagia de alma en alma; el Flagellante es el que más contagia, y la procesión que pretendía salvar es la que enferma.
- **La Disciplina.** Quien camina sin oficio se azota cada vez más: camina más despacio y contagia más. Un *disciplinato* ocupado es uno que no se hace daño.
- **El Maestro Lapo** cierra la procesión. No acepta oficios. Si muere, la Compagnia entra en pánico; si llega a la salida, el resto lo sigue con más ritmo. Y en el nivel 29, entre los falsos consejeros, una de las llamas habla con su voz.

Cuando solo queda el Maestro, **Enter** lo deja atrás.

---

## 4. Los nueve oficios

Como en Lemmings, cada botón de la predela dice **lo que hace**. Al pasar el ratón por encima aparece la explicación completa y el nombre italiano. Al pasarlo por un alma se ve qué está haciendo («Caminando», «Construyendo escalera», «¡Va a explotar!») y qué lleva encima («escala», «planea», «cura», «con fiebre»).

| Tecla | Botón | Nombre | Qué hace | Raíz histórica |
|---|---|---|---|---|
| 1 | **ESCALAR** | Pellegrino | Trepa paredes verticales (permanente) | El peregrino y su bordón |
| 2 | **PLANEAR** | Gerione | Baja planeando desde cualquier altura (permanente) | Gerión baja a Dante en espiral (*Inf.* XVII) |
| 3 | **EXPLOTAR** | Bubbone | Cuenta cinco segundos y revienta: abre un cráter | El bubón de la peste |
| 4 | **BLOQUEAR** | Flagellante | Se planta; los demás se dan la vuelta. Contagia | La procesión que no avanza |
| 5 | **ESCALERA** | Capomastro | Doce peldaños hacia delante y arriba | Los maestros de obra; Brunelleschi |
| 6 | **EXCAVAR** | Piagnone | Túnel horizontal a golpes | Los *piagnoni* de Savonarola |
| 7 | **PICAR** | Minatore | Excava en diagonal hacia abajo | Los pozos de Malebolge |
| 8 | **CAVAR** | Becchino | Pozo vertical; entierra focos de peste | El sepulturero de 1348 |
| 9 | **CURAR** | Medico | Inmune; cura la peste a quien pasa a su lado y apaga los focos (permanente) | El médico de la peste (*licencia*: la máscara es del s. XVII) |

**Los oficios son infinitos.** Las únicas excepciones son las de la propia Commedia: en el Paraíso no existen Explotar ni Cavar; en el último cielo desaparece Bloquear; y en la cornisa de los perezosos nadie puede pararse. En el Paraíso, un Flagellante plantado se convence de seguir con un clic.

**Dies Irae** (mantener Supr dos segundos, o N dos veces) convierte a toda la Compagnia en Bubbone. Es humillante, como en el original, y suma 5 de Peso.

---

## 5. Las palle, el Peso y la Moria

Las palle están repartidas por el camino. Un alma que pasa por encima la recoge y va al escudo, que tiene **8 huecos en el Inferno (Cosimo), 7 en el Purgatorio (Piero) y 6 en el Paraíso (Lorenzo)**. Se arman con **Q W E R T Y U I** y se usan con un clic.

| Palla | Teoría del origen | Poder | Peso |
|---|---|---|---|
| **del Cambio** (bezante) | Monedas del Arte del Cambio | Soborna a un guardián. En el Purgatorio, **C** compra un segundo intento: un 40 % más de días. Con el Ángel no funciona: la gracia no se compra (+5 de Peso) | +2 |
| **Medicinale** (píldora) | Médici = médicos | Cura la Moria en un radio y da 15 s de inmunidad | +1 |
| **d'Arancia** (naranja) | Los naranjos del Palazzo Medici | Señuelo: atrae a la horda o distrae a Cerbero, la loba, los centauros y las harpías. Clic derecho para lanzarla | +1 |
| **del Mecenate** (encargo) | Lo que los Médici hicieron con su dinero | **Tab** elige artista. **Brunelleschi**: un puente, o una cúpula contra la lluvia de fuego. **Botticelli**: revela el mapa y las cornisas ocultas. **Caravaggio**: el *Lume*, un haz oblicuo que deja de azotar a quien toca | +3 |
| **della Congiura** (26-IV-1478) | La conjura de los Pazzi | Aplaca a cualquier guardián o intercambia a dos almas. En el Cocito, cada una usada deja un alma congelada en la Antenora | +4 |
| **del Giglio** (lirio azul) | Luis XI, 1465 | Gracia prestada: amortigua una caída mortal por alma y limita el Peso a 30. En el nivel 100 es lo último que hay que **soltar** | 0 |

**Combo «Palle, palle, palle!»**: tres palle en diez segundos y la Compagnia corre al doble, sin pánico.

**El Peso** se arrastra de nivel en nivel. En el Purgatorio frena a quien escala y construye, y se hace visible: piedras a la espalda de los soberbios. Se quema así:

- devolviendo palle en la cornisa de los avaros (Mayús + tecla, −3 cada una);
- cruzando el muro de fuego de los lujuriosos (−10);
- en el Leteo, si es menor de 15;
- con la magnanimidad de Panfilo en la Giornata X.

**La Moria** tiene cuatro estados: sano → fiebre (más lento, contagia por contacto) → bubón (muy lento, solo acepta Explotar o Curar) → muerte. Un cadáver sin enterrar se vuelve **foco**. La curan el Medico, la Palla Medicinale y el fuego de la séptima cornisa; el Becchino entierra los focos.

---

## 6. La Commedia: 101 niveles

Cada nivel se genera por tramos con solución conocida (muro, foso, caída, mina, losa, cornisa, guardián, barca…), sobre la geografía de Dante. El Infierno es un embudo que baja; el Purgatorio, una montaña que sube; en el Paraíso **la gravedad tira hacia la luz** y la Compagnia cae hacia arriba.

| Niveles | Lugar | Lo que lo hace distinto |
|---|---|---|
| 0 | Florencia, 1348 | Ratas, focos de peste y un niño huérfano (Michelangelo) que se une a la fila |
| 1 | Selva oscura | Tres caminos: la lonza y el león cierran el de arriba; la loba, el de abajo |
| 2–3 | Antinferno | Los ignavos siguen un estandarte que no va a ninguna parte |
| 4 | Aqueronte | Caronte cobra el óbolo… o el rodeo durísimo: una pasarela sobre su cabeza |
| 5 | Limbo | Nadie muere; Homero, Aristóteles y Averroes recitan su verso |
| 6 | Lujuriosos | La bufera arrastra a quien cae; Paolo y Francesca pasan volando |
| 7–8 | Golosos | Cerbero, lluvia sucia |
| 9–10 | Avaros | Peñas que ruedan |
| 11–12 | Estigia | **La barca de Flegias**, que no zarpa sin el óbolo |
| 13–14 | Dite | Las Furias; el mensajero del cielo abre la puerta |
| 15–16 | Herejes | Sepulcros que llamean; llega la bula de Clemente VI |
| 17–21 | Violentos | Flegetonte de sangre, bosque de los suicidas (excavar cuesta Peso), arenal con lluvia de fuego |
| 22 | Gerión | La gran caída |
| 23–31 | Malebolge | Una bolgia por nivel: fango, pies ardiendo, adivinos al revés, pez, capas de plomo, serpientes, llamas que hablan, falsarios |
| 32 | Pozo de los gigantes | **Anteo** baja a cada alma al fondo |
| 33 | Cocito | Hielo resbaladizo y el peaje de la traición |
| 34 | Lucifer | Se baja por su pelo y, **en el centro de la Tierra, la gravedad se invierte** |
| 35–36 | Playa de Catón | El junco |
| 37–40 | Antepurgatorio | Esperar es trabajo; Caravaggio espera entre los muertos violentos |
| 41 | Puerta de san Pedro | Siete P en la frente; el soborno no sirve |
| 42–63 | Las siete cornisas | Soberbios (piedras), envidiosos (ojos cosidos), iracundos (humo), perezosos (no se paran), avaros (devolver palle), golosos (árboles), lujuriosos (muro de fuego) |
| 64–65 | Hoguera de las Vanidades | El fuego sube; Savonarola predica; hay que salvar las pagine |
| 66–67 | Paraíso terrestre | Leteo y Eunoè; Virgilio se despide |
| 68–99 | Los nueve cielos y el Empíreo | Luna (plataformas que van y vienen), Mercurio (palle que pesan al cogerlas), Venus (las almas solas van despacio), el Sol, la cruz de Marte, el *DILIGITE IUSTITIAM* de Júpiter, la escala de oro y el silencio de Saturno, los exámenes de las Estrellas fijas, el Primum Mobile (el Peso no asciende), la Rosa |
| 100 | La visión | Soltar el lirio |

Cada nivel tiene su **pagina** escondida: 101 versos reales de Dante y Boccaccio para salvar de la hoguera.

---

## 7. Las Giornate del Decamerón

Cada diez niveles, la Compagnia descansa en la villa de los diez narradores. El rey o la reina de la jornada comenta la partida e impone una regla a los diez niveles siguientes.

| Giornata | Niveles | Reina / Rey | Regla |
|---|---|---|---|
| I | 1–10 | Pampinea | Ninguna: se aprende |
| II | 11–20 | Filomena | Una caída por nivel resucita si otra alma llega a su cuerpo |
| III | 21–30 | Neifile | Oficios de sobra escondidos por el camino |
| IV | 31–40 | Filostrato | Las parejas no se separan: si cae una, cae la otra (el oficio salva) |
| V | 41–50 | Fiammetta | Las parejas no se contagian |
| VI | 51–60 | Elissa | La naranja llega más lejos |
| VII | 61–70 | Dioneo | Los señuelos duran el doble |
| VIII | 71–80 | Lauretta | Una palla de cada nivel es falsa |
| IX | 81–90 | Emilia | Ninguna: respiro |
| X | 91–100 | Panfilo | Cada alma por encima del mínimo resta 1 de Peso |

**El Privilegio de Dioneo** (tecla D): una vez por jornada, quince segundos sin la regla del lugar (noche, humo, viento, hielo…).

---

## 8. Finales

| Final | Condición | Qué ocurre |
|---|---|---|
| **I · La Rosa Cándida** | Más del 70 % de las almas salvadas en toda la Commedia, Peso 0 y el lirio soltado | La Compagnia, sin escudo ni látigo, entra en la Rosa. *L'amor che move il sole e l'altre stelle* |
| **II · Il Limbo** | Entre el 40 y el 70 %, o con Peso | Llegan al Empíreo pero no pueden mirar; vuelven al castillo de los sabios |
| **III · I Trentatré Giorni e Mezzo** | Menos del 40 %, o el Maestro llega vivo al final | El Maestro cruza solo; la puerta da a Florencia, 1348. La procesión vuelve a empezar |

---

## 9. Modos de juego

| Modo | Qué es |
|---|---|
| **Campaña** | Los 101 niveles en orden. El Peso, el escudo, el Maestro y las traiciones se arrastran de un nivel al siguiente. Mapa de la Commedia con el embudo, la montaña y las esferas |
| **Giudizio del giorno** | Un nivel nuevo cada día, generado con la fecha como semilla: es el mismo para todos. Guarda tu mejor resultado del día |
| **Infinito** | Círculos generados uno tras otro hasta que la Compagnia falle. Cuenta la racha y la mejor racha |
| **Nivel propio** | `--custom nivel.json` carga cualquier nivel en el formato del diseño. `--export-levels` escribe los 101 como punto de partida |
| **Demos** | **V** en el mapa o en la previa reproduce la solución de referencia del nivel |
| **Repeticiones** | **S** en la pantalla de resultado guarda la partida; `--replay fichero.json` la reproduce tick a tick |

Los niveles generados (diario e infinito) **calibran su mínimo al vuelo**: el juego los resuelve con su solución de referencia antes de enseñártelos y nunca exige más de lo que esa solución consigue.

---

## 10. Controles

### Ratón y teclado

| Acción | Tecla |
|---|---|
| Elegir oficio | **1–9**, rueda o clic en la predela |
| Asignar oficio | Clic izquierdo sobre el alma |
| Armar y usar palla | **Q W E R T Y U I**, luego clic |
| Lanzar naranja | Clic derecho |
| Artista del Mecenate | **Tab** con la palla armada |
| Devolver palla (avaros) | **Mayús** + su tecla |
| Segundo intento (Purgatorio) | **C** |
| Privilegio de Dioneo | **D** |
| Cadenza (ritmo de salida) | **+ / −** |
| Pausa / un paso | **Espacio** / **.** |
| Velocidad ×1 → ×2 → ×4 → ×8 | **F** |
| **Rebobinar 3 segundos** | **Retroceso** |
| Reiniciar el nivel | **F5** |
| Cámara | Flechas, bordes de la pantalla, minimapa o botón central del ratón |
| Modo foto / captura | **H** oculta el HUD · **F12** guarda una captura |
| Dies Irae | Mantener **Supr** 2 s (o **N** dos veces) |
| Dejar atrás al Maestro | **Enter**, cuando solo queda él |
| Música / pantalla completa | **M** / **F11** |

### Mando (SDL GameController: Xbox, PlayStation, Switch Pro, Steam Deck)

| Acción | Mando |
|---|---|
| Mover el cursor / la cámara | Stick izquierdo / stick derecho |
| Asignar | A |
| Cambiar de oficio | LB / RB |
| Lanzar naranja | X |
| Elegir palla / usarla | Cruceta izquierda-derecha / Y |
| Cadenza | LT / RT |
| Pausa / velocidad | Start / clic del stick derecho |
| Privilegio de Dioneo | Select |
| Dies Irae | Select + Start durante 2 s |
| Menús | Cruceta, A para aceptar, B para volver |

---

## 11. Opciones y accesibilidad

Desde **Opciones** en el menú principal; todo se guarda entre partidas.

| Opción | Para qué |
|---|---|
| Música | Encender o apagar las pistas generadas |
| Voces | El recitado en italiano de cada mensaje |
| Subtítulos | Español, inglés o italiano moderno |
| Luz y bloom | Alta o baja (también `--lowfx`) |
| Volumen | Diez niveles |
| Pantalla completa | También con F11 o `--fullscreen` |
| **Movimiento** | «Reducido» quita el temblor de pantalla y el grano de película |
| **Iconos de enfermedad** | Un «!» amarillo para la fiebre y una cruz roja para el bubón: la información no depende solo del color |
| **Alto contraste** | Sube la luz ambiente de los niveles más oscuros |
| **Sombras de los oficios** | Al apuntar a un alma, una línea de puntos enseña por dónde irá la escalera, el túnel, la mina, el pozo o el radio de la explosión y de la cura |

---

## 12. Un juego de 2026: la superpensada

### Diagnóstico

La pregunta «¿qué gráficos de 2026 le faltan?» estaba mal planteada. El juego ya tenía iluminación dinámica, bloom y partículas; lo que separa un remake moderno de Lemmings de uno de 1991 no es el píxel, sino **cuánto castiga al jugador por equivocarse**. En 1991 un error a los ocho minutos obligaba a repetir el nivel entero; en 2026 eso se considera mal diseño. Las referencias del género (NeoLemmix, *Lemmings: Can You Dig It?*, los Lemmings de móvil) convergen en lo mismo:

1. **Deshacer y experimentar sin miedo** (rebobinado, paso a paso, previsualizar el efecto de un oficio).
2. **Razones para volver** (estrellas, récords, logros, contenido diario y sin fin).
3. **Que nadie se quede fuera** (accesibilidad, mando, subtítulos, opciones de movimiento).
4. **Que la comunidad pueda crear** (formato de nivel abierto).

### El consejo deliberó

- **El diseñador de puzles** (la escuela de NeoLemmix): el rebobinado y las sombras de los oficios valen más que cualquier efecto gráfico, porque convierten el ensayo y error en pensamiento.
- **El ingeniero**: el rebobinado es barato *porque la simulación ya era determinista*. Una copia del mundo cada dos segundos (≈1 MB) y un registro de órdenes bastan. La única trampa eran las vistas de numpy del terreno invertido, que se rehacen al volver.
- **El diseñador de producto**: el diario y el infinito multiplican la vida del juego sin escribir un nivel más, siempre que cada nivel generado **se pruebe a sí mismo antes de enseñarse**.
- **La voz de la accesibilidad**: el estado de salud de las almas solo se veía por el tono de color; eso excluye a uno de cada doce hombres. Formas además de colores, y un interruptor para el temblor de pantalla.
- **El escéptico**: las tablas de clasificación en línea, el guardado en la nube o el Workshop de Steam rompen la regla de un solo fichero y fuera de línea. No se hacen.
- **El abogado del diablo**: con oficios infinitos y rebobinado, ¿dónde está el reto? En el Peso, en la Moria, en el tiempo y en las estrellas: la tercera estrella exige salvar las cien almas.

### Mejoras implementadas

| Área | Mejora | Estado |
|---|---|---|
| Calidad de vida | **Rebobinar** tres segundos (Retroceso), las veces que quieras | ✅ |
| Calidad de vida | **Paso a paso** en pausa (tecla «.») | ✅ |
| Calidad de vida | Velocidades **×1, ×2, ×4 y ×8** | ✅ |
| Calidad de vida | **Reinicio** instantáneo (F5) | ✅ |
| Calidad de vida | **Sombras de los oficios**: previsualización de escalera, túnel, mina, pozo, cráter y radio de cura | ✅ |
| Calidad de vida | Los botones dicen lo que hacen y el alma bajo el cursor dice qué está haciendo | ✅ |
| Calidad de vida | Oficios infinitos | ✅ |
| Rejugabilidad | **Estrellas** por nivel y **récords** (más almas; en caso de empate, menos tiempo) | ✅ |
| Rejugabilidad | **18 logros**, con aviso en pantalla | ✅ |
| Rejugabilidad | **Giudizio del giorno**, el desafío diario con semilla de la fecha | ✅ |
| Rejugabilidad | Modo **Infinito** con racha | ✅ |
| Rejugabilidad | 101 pagine coleccionables con versos reales | ✅ |
| Accesibilidad | **Iconos de enfermedad**, además del color | ✅ |
| Accesibilidad | **Movimiento reducido** (sin temblor ni grano) | ✅ |
| Accesibilidad | **Alto contraste** | ✅ |
| Accesibilidad | Subtítulos en tres idiomas y voz | ✅ |
| Accesibilidad | **Mando** completo, con cursor virtual | ✅ |
| Herramientas | **Modo foto** (H) y capturas (F12) | ✅ |
| Herramientas | Exportar e importar niveles en JSON | ✅ |
| Herramientas | Repeticiones deterministas | ✅ |
| Herramientas | `--selftest` y `--calibrate` | ✅ |
| Gráficos | Tenebrismo dinámico, bloom en dos escalas, parallax, niebla, viñeta, grano | ✅ |
| Sonido | Música por cantica, efectos y voz, todo sintetizado | ✅ |

### Pendiente (y por qué)

| Mejora | Por qué no está todavía |
|---|---|
| Redefinir teclas | Es útil pero laborioso de hacer bien (conflictos, mando, guardado). Es lo siguiente en la lista |
| Editor de niveles dentro del juego | Hoy se edita el JSON a mano; un editor visual cabe en el fichero, pero duplica su tamaño |
| Menús traducidos | Solo los subtítulos están en tres idiomas; la interfaz sigue en español |
| Paletas para daltonismo completas | Ya hay iconos de forma; faltaría remapear también los colores de las palle y del terreno |
| Vibración del mando | pygame lo permite, pero sin un mando físico no se puede probar con honestidad |
| Tablas de clasificación en línea, nube, Workshop | Exigen servidor y cuentas: rompen la regla de un solo fichero fuera de línea. Descartado a propósito |
| Voz humana | Una voz grabada no cabe en código; la síntesis pronuncia de verdad, pero suena robótica |

---

## 13. Gráficos y sonido

**Resolución lógica 640×360**, escalada en enteros: el pixel art se mantiene nítido a cualquier tamaño de ventana. Cada fotograma tarda entre 6 y 10 ms incluso con cien almas en pantalla.

El orden de dibujado es este:

1. **Fondo por capas** con parallax: las hogueras de Doré con rayado de grabado, la Florencia de la cúpula de Brunelleschi, la montaña en terrazas, las esferas de Giovanni di Paolo, el Lucifer helado. Encima, las capas animadas de cada cielo: las coronas del Sol, la cruz de Marte, el águila de Júpiter, la escala de Saturno.
2. **Terreno** con textura por estratos y ruido fractal, sombreado de claroscuro (los bordes iluminados, el interior hundido en sombra) y **vetas incandescentes** que brillan en el Infierno.
3. **Peligros animados**: líquidos con oleaje y color propio por bolgia, fuego, el remolino violeta del centro de la Tierra.
4. **Entidades**: almas con contorno de 1 px, guardianes, barca, gigante, serpientes, árboles, palle con destellos.
5. **Luz**: un mapa de luz a media resolución que se multiplica sobre la escena. Ambiente por tema, una vela por alma, braseros, palle y el haz diagonal del *Lume* de Caravaggio.
6. **Bloom** en dos escalas sobre la capa emisiva.
7. **Posproceso**: viñeta, grano de película, temblor de pantalla en las explosiones.

Lo que se cae hacia arriba se dibuja en una **capa invertida** que se voltea al final, con su propia luz y su propio bloom.

**Sonido**, todo sintetizado con numpy al arrancar:

- **Inferno**: el *Dies irae* en canto llano sobre un bordón, con cadenas y tambor.
- **Purgatorio**: una lauda original en modo dórico a dos voces.
- **Paraíso**: polifonía de acordes con campanas; Saturno, en silencio.
- **Florencia y la villa**: un laúd en Karplus-Strong y la campana de difuntos.
- **Efectos**: más de veinte, cada uno sintetizado.
- **Voz**: un conversor de grafemas italianos a fonemas (*gli*, *gn*, *sc*, *ch*, geminadas) y un sintetizador por formantes que recita en italiano cada mensaje, con el tono de quien habla. Se genera en un hilo aparte para no congelar la imagen.

---

## 14. Arquitectura del código

Un único fichero, ordenado en secciones:

| § | Sección | Qué contiene |
|---|---|---|
| 1 | Constantes | Física (las de Lemmings), tiempos de la Moria, costes del Peso, enumeraciones de oficios y estados |
| 2 | Sprites | Pixel art escrito como texto; variantes del Maestro y del niño por recoloreado |
| 3 | Terreno | Máscara de bytes por píxel; `FlipTerrain` ve la misma memoria del revés (vistas de numpy) para quien cae hacia arriba |
| 4 | La Commedia | `place_info`, `MapBuilder` (tramos con su regla de solución), `build_level`, Lucifer, Paraíso invertido, variantes generadas, `parse_map` |
| 5 | La Compagnia | `World`: simulación determinista a 20 Hz que no sabe que pygame existe. `Autopilot`, `Replay`, `simulate`, instantáneas para rebobinar |
| 6 | Render | `Backdrop`, `Atmosphere`, `FX`, `Renderer` (luz, bloom, capa invertida), sombras de los oficios |
| 7 | Sonido | Síntesis musical, efectos, conversor de grafemas a fonemas y voz por formantes |
| 8 | Textos | Versos, códice, Brigata, finales, subtítulos en tres idiomas |
| 9 | Interfaz | `App`: título, mapa, villa, previa, partida, resultado, finales, opciones, logros, mando |
| 10 | Pruebas | Selftest, calibración, JSON |
| 11 | Principal | `main` y las órdenes de línea de comandos |

Decisiones que sostienen el resto:

- **Determinismo total.** Mismo nivel y mismas órdenes, misma partida, tick a tick. De ahí salen las repeticiones, las demos, el validador, la calibración y el rebobinado.
- **Soluciones de referencia.** Cada tramo de nivel sabe cómo se resuelve. El autopiloto aplica esas reglas y demuestra que el nivel es posible.
- **Simulación y dibujo separados.** El mundo emite eventos (sonidos) y efectos (partículas) que la interfaz consume.

---

## 15. Pruebas y calibración

```bash
python pydanteshell.py --selftest          # todo (unos minutos)
python pydanteshell.py --selftest --quick  # uno de cada diez niveles
python pydanteshell.py --calibrate         # remedir los mínimos
```

El selftest comprueba:

- **la física**: escalones, caídas, escalera, cráteres, pozos, túneles, minas, escalada, bloqueo;
- **la Moria y el Medico**, las palle y los guardianes;
- **la gravedad invertida**, Anteo, la cúpula y las plataformas de la Luna;
- **los subtítulos y la pronunciación** del italiano, y un nivel exportado a JSON y vuelto a leer que se juega igual;
- **el rebobinado**: rebobinar y rehacer da exactamente la misma partida;
- **un desafío diario** resoluble, y la regla de las estrellas;
- **los 101 niveles** resueltos por su solución de referencia en dos supuestos: una Compagnia ligera (sin Peso ni palle) y una cargada (Peso 30 y escudo lleno). La partida se reproduce idéntica desde su registro.

La **calibración** mide cuántas almas salva cada solución en el peor de esos dos supuestos. El mínimo de cada nivel nunca supera esa cifra, así que **ningún nivel es imposible**, venga como venga la Compagnia.

---

## 16. Formato de nivel (JSON)

Es el formato del documento de diseño, con el mapa en texto. Solo `map` es obligatorio; el resto tiene valores por defecto.

```json
{
  "name": "Mi Estigia",
  "cantica": "inferno",
  "theme": "fango",
  "count": 100,
  "release_rate": 50,
  "save_required": 60,
  "minutes": 6,
  "map": ["....", "...E", "####"],
  "palle": [{"type": "cambio", "x": 210, "y": 264}],
  "guards": [{"type": "flegias", "x": 300, "y": 264}],
  "hazards": {"boats": [[128, 192, 264]], "vents": [], "boulders": []},
  "mods": ["night"],
  "moria": {"initial_infected": 2, "rats": true},
  "reference_solution": [{"skill": "piagnone", "x": 284, "dir": 1}]
}
```

Leyenda del mapa (cada carácter es un bloque de 8×8 px):

| Carácter | Significado |
|---|---|
| `.` | Aire |
| `#` | Roca |
| `S` | Pietra serena (indestructible) |
| `<` `>` | Muro de sentido único |
| `/` `\` `_` | Rampa que sube, rampa que baja, medio bloque |
| `~` | Líquido letal |
| `^` | Fuego |
| `%` | Fuego que purifica |
| `\|` | Centro de la Tierra (invierte la gravedad) |
| `E` `X` | Entrada y salida |
| `U` `x` | Entrada y salida para quien cae hacia la luz |

---

## 17. Historia, tesis y licencias

El juego mezcla siglos a sabiendas y lo dice. El **Códice** del menú principal recoge treinta entradas marcadas como `[dato]`, `[tesis]` o `[licencia]`. Algunas:

- **[dato]** Los flagelantes de 1349 vestían hábito blanco con cruz roja y prometían salvación en 33 días y medio. Clemente VI los condenó el 20 de octubre de 1349.
- **[dato]** Las palle: 8 en el escudo de Cosimo, 7 en el de Piero y 6 en el de Lorenzo; la azul con lises, concesión de Luis XI en 1465.
- **[dato]** Las bolge de Malebolge, Anteo, la barca de Flegias, la lluvia de fuego, las siete P, el *DILIGITE IUSTITIAM*: todo está en Dante.
- **[tesis]** Caravaggio en el Antepurgatorio, entre los muertos violentos que se arrepintieron a última hora.
- **[tesis]** La gravedad hacia la luz del Paraíso.
- **[licencia]** El Maestro cierra la fila en vez de abrirla, para que protegerlo sea posible.
- **[licencia]** El niño Michelangelo en Florencia en 1348 (fue en Milán, en 1577).
- **[licencia]** La máscara de pico del Medico es del siglo XVII.
- **[licencia]** La pasarela de Caronte y la cúpula de Brunelleschi usada como paraguas.
- **[licencia]** La voz recita en italiano moderno, no en el del Trecento.

Todos los versos citados son de la *Commedia* y del *Decameron*, que son de dominio público.

---

## 18. Licencia

- **Código**: MIT.
- **Textos de Dante y Boccaccio**: dominio público.

*Lemmings* es una marca de sus respectivos titulares. Este proyecto toma prestado el género, no el nombre, los personajes ni los recursos.

> *E quindi uscimmo a riveder le stelle.*
