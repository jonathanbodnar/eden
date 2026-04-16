"""Ingest batch 2 of visual library: architectural/structural artifacts."""
import asyncio
import hashlib
import json
import logging

import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ARTIFACTS = [
    # === ANATOLIA ===
    {"title": "Göbekli Tepe Enclosure D (Full Architectural Layout)", "location": "Şanlıurfa, Turkey", "culture": "Pre-Pottery Neolithic", "region": "Anatolia", "date_start": -9600, "date_end": -8800, "date_label": "~9600 BCE",
     "description": "The largest and best-preserved enclosure at Göbekli Tepe. Roughly circular, approximately 20 meters in diameter, defined by a low stone bench-wall with 12 T-shaped pillars embedded in it, plus two massive central pillars (Pillars 18 and 31) standing over 5 meters tall. The central pillars show carved arms, hands, belts, and loincloths — anthropomorphic features. Animal reliefs on perimeter pillars include foxes, boars, snakes, cranes, and aurochs. A carved boar and fox appear on Pillar 27. The floor is a polished terrazzo-like surface (burnt lime and clay). A stone bench runs along the interior wall between pillars. Two porthole stones (pierced slabs) served as controlled entry points."},
    {"title": "Göbekli Tepe Pillar 18 (Central Monolith Pair)", "location": "Şanlıurfa, Turkey", "culture": "Pre-Pottery Neolithic", "region": "Anatolia", "date_start": -9000, "date_end": -8500, "date_label": "~9000 BCE",
     "description": "One of two central T-shaped pillars in Enclosure D, standing approximately 5.5 meters tall and weighing an estimated 10 tons. Carved from a single block of local limestone. Features include human arms in low relief running down the sides, hands with fingers meeting at the front below a carved belt and loincloth/fox-skin garment. A carved fox appears on the narrow side. The pillar's flat 'T' head represents a stylized human head in profile. Pillar 31 (its pair) is similar but with different animal reliefs. Together they dominate the center of the enclosure, facing the southeastern entrance."},

    # === LEVANT ===
    {"title": "Jericho Neolithic City Wall", "location": "Tell es-Sultan, West Bank", "culture": "Pre-Pottery Neolithic A", "region": "Levant", "date_start": -8000, "date_end": -7500, "date_label": "~8000 BCE",
     "description": "A dry-stone wall approximately 3.6 meters tall and 1.8 meters thick at the base, encircling the Pre-Pottery Neolithic settlement at Tell es-Sultan. Constructed of undressed fieldstone. Associated with a ditch cut into bedrock (8.2 meters wide, 2.7 meters deep) outside the wall. The circular stone tower (8.5 meters tall) is built against the inner face of the wall. The full perimeter enclosed approximately 2.5 hectares. One of the oldest known defensive or boundary wall systems in the world. Excavated by Kathleen Kenyon in the 1950s."},

    # === ÇATALHÖYÜK ARCHITECTURE ===
    {"title": "Çatalhöyük Rooftop Entry Architecture", "location": "Konya, Turkey", "culture": "Neolithic", "region": "Anatolia", "date_start": -7000, "date_end": -6000, "date_label": "~7000 BCE",
     "description": "Rectangular mud-brick houses with no ground-level doors or windows. Entry was through an opening in the flat roof, accessed by a wooden ladder that also served as the main interior feature — the ladder descended next to the hearth and oven. Rooftops served as streets, work areas, and communal space. Interior walls were plastered and periodically painted. Houses were built directly against each other in a honeycomb pattern sharing party walls. Platforms inside served as sleeping, working, and burial areas (the dead were buried beneath floor platforms)."},
    {"title": "Çatalhöyük Streetless Urban Layout", "location": "Konya, Turkey", "culture": "Neolithic", "region": "Anatolia", "date_start": -7000, "date_end": -6000, "date_label": "~7000 BCE",
     "description": "A densely packed settlement of approximately 8,000 people with no streets, alleys, or ground-level pathways between buildings. Houses share walls and are accessed only from the roof. The rooftop level forms the circulation surface — a continuous elevated plane with openings for entry into each dwelling. Midden areas (refuse dumps) accumulate between house clusters. Buildings were demolished and rebuilt on their own foundations over centuries, creating a settlement mound (tell) rising 21 meters. Excavated area reveals a uniform grid of rectangular rooms approximately 25 square meters each."},

    # === NORTH AFRICA ===
    {"title": "Nabta Playa Megalith Alignments (Astronomical)", "location": "Nubian Desert, Egypt", "culture": "Neolithic Pastoral", "region": "North Africa", "date_start": -6000, "date_end": -5000, "date_label": "~6000 BCE",
     "description": "Lines of standing stones radiating outward from the central stone circle. Multiple alignments of megaliths, some over 2 meters tall, placed in rows oriented toward specific astronomical events including the summer solstice sunrise. One alignment points to the bright star Sirius. 'Calendar Circle' stones mark the position of the sun at the summer solstice. Complex A consists of a large shaped stone placed over a bedrock sculpture. Located in a dry lake basin (playa) that held seasonal water during the Neolithic wet phase."},

    # === SAHARA ===
    {"title": 'Tassili n\'Ajjer "Cattle Period" Pastoral Scenes', "location": "Tassili n'Ajjer, Algeria", "culture": "Saharan Neolithic (Pastoral Period)", "region": "Sahara / North Africa", "date_start": -5000, "date_end": -2000, "date_label": "~5000 BCE",
     "description": "Rock paintings depicting herds of long-horned cattle in profile, herders with bows, encampments with domed huts, and daily pastoral life. Cattle are shown in various colors — white, red, brown, piebald — with careful attention to horn shapes and body markings. Scenes include milking, watering at pools, and driving herds. Human figures are slender with body paint or scarification marks. Painted in the 'Bovidian' or 'Pastoral' style period (c. 5000–1500 BCE) of the Tassili n'Ajjer rock art sequence."},

    # === EUROPEAN PETROGLYPHS ===
    {"title": "Val Camonica Solar Symbol Petroglyphs", "location": "Val Camonica, Lombardy, Italy", "culture": "Neolithic through Bronze Age", "region": "Europe", "date_start": -6000, "date_end": -1000, "date_label": "~6000 BCE",
     "description": "Rock engravings of solar symbols including rayed circles, concentric circles with radiating lines, and the 'Camunian rose' (a swastika-like motif within a circle). Some solar discs are shown carried on poles or above standing figures ('praying' figures with upraised arms). Sun symbols appear in association with plowing scenes, animals, and warriors. Carved by pecking into glacially polished sandstone surfaces. Part of the larger Val Camonica complex of 300,000+ engravings."},
    {"title": "Alta Boat Procession Carvings", "location": "Alta, Norway", "culture": "Arctic Hunter-Gatherer", "region": "Scandinavia", "date_start": -5000, "date_end": -2000, "date_label": "~5000 BCE",
     "description": "Petroglyphs depicting processions of large boats with high prows and sterns, carrying multiple human figures shown as vertical lines. Boats range from small craft with a few figures to large vessels with 20+ occupants. Some boats show animal-head prows (elk or reindeer). Scenes include boats alongside groups of reindeer, elk hunting from boats, and fishing with nets. Carved into flat shoreline rock surfaces at the Alta fjord. The boat carvings are among the most numerous motifs at the site."},

    # === MEGALITHIC EUROPE ===
    {"title": "Newgrange Interior Passage Alignment (Winter Solstice Light)", "location": "County Meath, Ireland", "culture": "Neolithic", "region": "Europe", "date_start": -3200, "date_end": -3000, "date_label": "~3200 BCE",
     "description": "A 19-meter-long passage built of large orthostats (upright stones) leading to a cruciform chamber with a corbelled roof rising 6 meters. Above the entrance, a 'roof box' opening (1 meter wide, 25 cm high) is precisely aligned so that at sunrise on the winter solstice (and a few days before and after), a beam of sunlight travels the full length of the passage and illuminates the back wall of the chamber for approximately 17 minutes. The passage rises 2 meters from entrance to chamber to facilitate the light beam's trajectory. Carved spirals and lozenges decorate stones in the passage and chamber."},

    # === MESOPOTAMIA ===
    {"title": "Uruk City Wall Foundations", "location": "Uruk (Warka), Iraq", "culture": "Sumerian (Early Dynastic)", "region": "Mesopotamia", "date_start": -3000, "date_end": -2500, "date_label": "~3000 BCE",
     "description": "Remains of a massive city wall encircling the ancient city of Uruk, extending approximately 9.5 kilometers with over 900 semicircular bastions (defensive towers). The wall enclosed an area of approximately 5.5 square kilometers — making Uruk the largest city in the world at the time. Constructed of mud-brick on stone foundations. Attributed to the legendary king Gilgamesh in Sumerian literature. The Eanna precinct (temple district) and Anu ziggurat complex lie within the walls. Population estimated at 40,000–80,000 at its peak."},
    {"title": "Ziggurat of Ur", "location": "Ur (Tell el-Muqayyar), Iraq", "culture": "Sumerian (Ur III Dynasty)", "region": "Mesopotamia", "date_start": -2100, "date_end": -2000, "date_label": "~2100 BCE",
     "description": "A stepped pyramid temple platform with a rectangular base measuring approximately 64 x 46 meters. Originally three stages rising to approximately 21 meters, topped by a temple to the moon god Nanna (Sin). The first stage survives to a height of 11 meters. Three monumental staircases converge at a gatehouse on the first terrace — one central (100 steps) and two flanking. Constructed of mud-brick core with a fired-brick and bitumen facing. Walls are slightly convex (entasis) to prevent optical illusion of concavity. Built by Ur-Nammu, completed by his son Shulgi. Partially restored by Leonard Woolley and later by Saddam Hussein."},
    {"title": "Eridu Temple Layer Sequence", "location": "Tell Abu Shahrain, Iraq", "culture": "Ubaid through Early Dynastic Sumerian", "region": "Mesopotamia", "date_start": -5000, "date_end": -2000, "date_label": "~5000–2000 BCE",
     "description": "Eighteen superimposed temple levels excavated at Eridu, the earliest Sumerian temple sequence known. The earliest level (Temple XVI, c. 5000 BCE) is a small single-room shrine (3.5 x 3.5 meters) with an altar and offering table. Successive rebuilds grow progressively larger, maintaining the same ground plan and orientation. By Temple VII (c. 3800 BCE), the building has a tripartite plan with a central hall, side chambers, and a stepped platform — the prototype for later ziggurats. Fish bones deposited as offerings in the earliest levels connect to the myth of Enki's city rising from the primordial waters."},
    {"title": "Ishtar Gate (Reconstructed and Original Fragments)", "location": "Babylon, Iraq", "culture": "Neo-Babylonian", "region": "Mesopotamia", "date_start": -575, "date_end": -575, "date_label": "~575 BCE",
     "description": "A double-arched gateway originally 14 meters tall, faced with glazed bricks in deep lapis-blue. Decorated with alternating rows of aurochs (bulls, sacred to Adad) and mushḫuššu dragons (sacred to Marduk) in molded relief, glazed in yellow and brown on the blue ground. The Processional Way leading to the gate was lined with 120 glazed-brick lions (sacred to Ishtar) in striding poses. Built by Nebuchadnezzar II. The reconstructed gate stands in the Pergamon Museum, Berlin (12 meters tall). Original fragments remain in situ and in the Iraq Museum, Baghdad."},

    # === EGYPT ===
    {"title": "Saqqara Step Pyramid Complex (Full Layout)", "location": "Saqqara, Egypt", "culture": "Old Kingdom Egyptian (3rd Dynasty)", "region": "Egypt", "date_start": -2667, "date_end": -2648, "date_label": "~2667 BCE",
     "description": "The funerary complex of Pharaoh Djoser, designed by Imhotep. The Step Pyramid (62 meters tall, six steps) is the centerpiece — the first monumental stone building in history. The complex is enclosed by a niched limestone wall (10.5 meters tall, 1,645 meters perimeter) with one real entrance and 14 false doors. Interior features include the South Court with boundary markers (B-shaped stones for the Heb-Sed festival), the House of the North and South (symbolic chapels), a Serdab (sealed room with a life-size Ka statue of Djoser looking out through two peepholes), and a subterranean network of 6 km of tunnels lined with blue faience tiles imitating reed matting."},
    {"title": "Giza Plateau Full Layout", "location": "Giza, Egypt", "culture": "Old Kingdom Egyptian (4th Dynasty)", "region": "Egypt", "date_start": -2560, "date_end": -2510, "date_label": "~2500 BCE",
     "description": "Three major pyramids on a diagonal alignment: Great Pyramid of Khufu (146 meters, 2.3 million blocks), Pyramid of Khafre (136 meters, appears taller due to higher ground, retains limestone casing at apex), and Pyramid of Menkaure (66 meters, partially granite-cased). Each pyramid has an associated mortuary temple on the east face, a causeway descending to a valley temple at the floodplain edge, and subsidiary queens' pyramids. The Great Sphinx (73 meters long, 20 meters tall) sits beside Khafre's valley temple, carved from a natural limestone outcrop. Workers' village and bakeries excavated south of the Sphinx. Three boat pits beside the Great Pyramid contained full-size cedar vessels."},
    {"title": "Khafre Valley Temple Megalithic Blocks", "location": "Giza, Egypt", "culture": "Old Kingdom Egyptian (4th Dynasty)", "region": "Egypt", "date_start": -2520, "date_end": -2494, "date_label": "~2500 BCE",
     "description": "A valley temple constructed of massive limestone core blocks (some weighing over 100 tons) faced with red granite from Aswan. The T-shaped interior hall contains 16 red granite monolithic pillars (each approximately 4 meters tall) supporting granite architraves. The floor is paved with alabaster. 23 emplacements for royal statues lined the walls (the famous Khafre diorite statue with Horus was found here). Walls are undecorated — the architectural effect relies entirely on the massive scale and polish of the stone. Connected to the pyramid by a 494-meter causeway."},

    # === INDUS VALLEY ===
    {"title": "Mohenjo-Daro Covered Street Drainage System", "location": "Mohenjo-Daro, Sindh, Pakistan", "culture": "Indus Valley Civilization", "region": "South Asia / Indus Valley", "date_start": -2500, "date_end": -1900, "date_label": "~2500 BCE",
     "description": "A network of brick-lined drains running along every major and minor street, covered with flat stone or brick slabs that could be lifted for cleaning. Individual houses connect to the street drains via small channels passing through the walls at floor level. Soak pits (cesspits) at intervals allow sediment to settle. Main drains are approximately 60 cm deep and 30 cm wide, built with precisely fitted fired bricks. The system represents the most advanced urban sanitation infrastructure of the ancient world — no contemporary civilization had comparable covered drainage."},
    {"title": "Dholavira Water Reservoir System", "location": "Dholavira, Kutch, Gujarat, India", "culture": "Indus Valley Civilization", "region": "South Asia / Indus Valley", "date_start": -2500, "date_end": -1900, "date_label": "~2500 BCE",
     "description": "A complex water management system in an arid environment. Sixteen or more reservoirs cut into bedrock and lined with stone, connected by channels. Two seasonal streams (Manhar and Mansar) are dammed and channeled into the reservoir system. The largest reservoir measures approximately 73 x 29 meters and 10 meters deep. Stone-cut steps provide access. Storm-water channels direct rainwater from the citadel and town into the reservoirs. The system stored an estimated 250,000 cubic meters of water — enough for 5,000 people through the dry season."},

    # === INDIA ===
    {"title": "Barabar Cave Polished Granite Interiors", "location": "Barabar Hills, Bihar, India", "culture": "Maurya Empire", "region": "South Asia", "date_start": -250, "date_end": -200, "date_label": "~250 BCE",
     "description": "Rock-cut caves excavated into hard gneiss/granite. The interior surfaces are polished to a mirror finish — the stone reflects light and images. The Lomas Rishi cave has an arched entrance carved to imitate a wooden structural facade with a lattice pattern. The Sudama cave interior is a rectangular chamber (10 x 5.8 meters) with a domed inner sanctum. Inscriptions by Emperor Ashoka dedicate the caves to the Ajivika sect. The polishing technique (known as 'Mauryan polish') was not replicated in later Indian rock-cut architecture. The caves produce distinctive acoustic resonance."},

    # === CHINA ===
    {"title": "Sanxingdui Ritual Pit Layout", "location": "Sanxingdui, Guanghan, Sichuan, China", "culture": "Ancient Shu Kingdom", "region": "East Asia / China", "date_start": -1200, "date_end": -1000, "date_label": "~1200 BCE",
     "description": "Eight rectangular pits (Pits 1–8) containing intentionally broken and burned bronze, gold, jade, and ivory objects deposited in layers. Pit 1 (4.6 x 3.5 meters): contained burned animal bones, jade, and bronze heads. Pit 2 (5.3 x 2.3 meters): contained the large standing bronze figure, bronze heads (some gold-foiled), the bronze tree, and jade objects. Pits 3–8 (excavated 2020–2022): yielded additional gold masks, bronze vessels, silk remnants, and ivory. Objects were deliberately broken, burned, and then carefully layered — a ritual termination deposit unlike anything else in Chinese archaeology."},

    # === AEGEAN ===
    {"title": "Knossos Multi-Level Palace Layout", "location": "Knossos, Crete, Greece", "culture": "Minoan", "region": "Aegean / Mediterranean", "date_start": -1700, "date_end": -1400, "date_label": "~1600 BCE",
     "description": "A sprawling palatial complex covering approximately 14,000 square meters on multiple levels built around a large central court (50 x 25 meters). The West Wing contains storage magazines with giant pithoi (storage jars), a throne room with a gypsum throne and griffin frescoes, and ritual areas. The East Wing descends four stories into the hillside with the 'Hall of the Double Axes' and the 'Queen's Megaron' with dolphin fresco. Features include light wells, pier-and-door partitions for flexible room configuration, a sophisticated drainage system with terracotta pipes, and the Grand Staircase with tapered Minoan columns. Over 1,300 rooms in the final palace phase."},
    {"title": "Akrotiri Multi-Story Buildings", "location": "Akrotiri, Santorini, Greece", "culture": "Minoan (Cycladic)", "region": "Aegean / Mediterranean", "date_start": -1600, "date_end": -1500, "date_label": "~1600 BCE",
     "description": "Two- and three-story stone buildings preserved to upper-floor level by volcanic burial. Xeste 3 has an elaborate lustral basin (sunken room for ritual) and painted frescoes of women gathering saffron. The West House contains the Miniature Frieze (ships, dolphins, harbors). Buildings feature cut-stone corners, timber-framed rubble walls (earthquake-resistant), indoor plumbing with terracotta pipes, and flush toilets connected to a sewage system. Streets are paved with flat stones with a drainage channel down the center. Windows with multiple openings and balconies face the streets. Population before the eruption estimated at 3,000–5,000."},

    # === ROMAN ===
    {"title": "Roman Concrete Harbor Structures (Cosa and Ostia)", "location": "Cosa and Ostia, Italy", "culture": "Roman", "region": "Mediterranean / Italy", "date_start": -200, "date_end": 100, "date_label": "~200 BCE",
     "description": "Harbor breakwaters and pier foundations constructed using opus caementicium (Roman concrete) placed underwater. At Cosa, a concrete pier was cast inside a wooden formwork directly into the sea (c. 170 BCE) — the oldest known marine concrete. At Portus (Ostia), Claudius and Trajan built massive concrete moles enclosing an artificial harbor basin. The concrete mix used volcanic ash (pozzolana) from the Bay of Naples region — specifically a mixture of lime, seawater, and volcanic tuff. Modern analysis shows the seawater triggered a crystal growth (Al-tobermorite) that actually strengthened the concrete over time, explaining its 2,000-year durability in saltwater."},

    # === MESOAMERICA ===
    {"title": "Teotihuacan Avenue of the Dead (Full Axial Layout)", "location": "Teotihuacan, Mexico", "culture": "Teotihuacano", "region": "Mesoamerica", "date_start": -100, "date_end": 250, "date_label": "~100 BCE",
     "description": "A monumental central avenue approximately 2.4 km long and 40 meters wide, oriented 15.5° east of true north. Lined with platforms, temples, and residential compounds on both sides. Major structures along the axis: Pyramid of the Moon (43 meters, at the north terminus), Pyramid of the Sun (65 meters, 225-meter base — third largest pyramid in the world, set to the east), the Ciudadela (Citadel compound with the Feathered Serpent Pyramid inside), and the Great Compound (possible marketplace). The avenue is not a road but a series of linked open plazas separated by platforms. Drainage channels run beneath. The entire layout reflects a planned urban design with astronomical alignments."},
    {"title": "Teotihuacan Residential Compounds", "location": "Teotihuacan, Mexico", "culture": "Teotihuacano", "region": "Mesoamerica", "date_start": -100, "date_end": 550, "date_label": "~100 BCE",
     "description": "Over 2,000 standardized apartment compounds housing the city's 100,000–200,000 residents. Each compound is roughly square (50–60 meters per side), enclosed by high windowless walls. Interior contains multiple apartments arranged around open courtyards with central altars and drainage systems. Rooms are roofed with concrete-like mortar on wooden beams. Walls are plastered and often painted with murals. Each compound housed 60–100 people, likely an extended family or occupational group. Tetitla, Tepantitla, and Atetelco compounds are famous for their well-preserved murals."},
    {"title": "Maya Sacbe (Raised White Road Systems)", "location": "Yucatán Peninsula, Mexico", "culture": "Classic Maya", "region": "Mesoamerica", "date_start": -300, "date_end": 900, "date_label": "~300 BCE+",
     "description": "Elevated causeways (sacbeob, singular sacbe — 'white road' in Yucatec Maya) connecting temple groups, plazas, and cities. Constructed of a limestone rubble core with dressed stone edges, surfaced with crushed white limestone (sascab) that was rolled and compacted. Widths range from 2 to 20 meters, heights from 0.5 to 2.5 meters above ground level. The longest known sacbe runs 100 km from Cobá to Yaxuná. Cobá alone has over 50 internal sacbeob connecting its site groups. Used for processions, trade, and possibly astronomical sighting lines."},
    {"title": "Tikal Acropolis Complex", "location": "Tikal, Petén, Guatemala", "culture": "Classic Maya", "region": "Mesoamerica", "date_start": -300, "date_end": 900, "date_label": "~300 BCE+",
     "description": "The North Acropolis is a massive platform (100 x 80 meters, 30 meters tall) containing over 100 buildings and the tombs of Tikal's earliest kings, with construction layers spanning 1,500 years. Temple I (Temple of the Great Jaguar, 47 meters) and Temple II (38 meters) face each other across the Great Plaza. The Central Acropolis is an administrative and residential palace complex of 45+ multi-room buildings on multiple levels. Temple IV (65 meters) is the tallest pre-Columbian structure in the Americas. Causeways connect the major groups across 16 square kilometers of settlement. Population at peak: 60,000–120,000."},

    # === SOUTH AMERICA ===
    {"title": "Caral Residential Complexes", "location": "Supe Valley, Peru", "culture": "Norte Chico (Caral)", "region": "South America / Andes", "date_start": -2600, "date_end": -2000, "date_label": "~2600 BCE",
     "description": "Residential areas flanking the monumental pyramids of Caral. Houses are constructed of cane (quincha) walls with wooden frames, plastered with mud. Larger residences for elites are built of stone with plastered interiors. Room sizes and construction quality vary, suggesting social differentiation. Some residences contain fire pits with possible ceremonial function. Artifacts include bone flutes (32 found), quipus (knotted string records), textiles, and carved bone and stone objects. No pottery, no evidence of weapons or defensive structures."},
    {"title": "Caral Irrigation Systems", "location": "Supe Valley, Peru", "culture": "Norte Chico (Caral)", "region": "South America / Andes", "date_start": -2600, "date_end": -2000, "date_label": "~2600 BCE",
     "description": "Canals diverting water from the Supe River to agricultural fields on the valley floor. The irrigation network supported cultivation of cotton (the primary crop — used for fishing nets traded with coastal communities), squash, beans, and guava. Canal intakes positioned to capture seasonal river flow. Fields are located on alluvial terraces. The agricultural-fishing exchange economy (inland cotton for coastal fish) sustained the civilization without pottery or grain agriculture — unique among early complex societies."},
    {"title": 'Chavín Temple "Black and White Portal"', "location": "Chavín de Huántar, Peru", "culture": "Chavín", "region": "South America / Andes", "date_start": -900, "date_end": -500, "date_label": "~900 BCE",
     "description": "The main entrance to the New Temple at Chavín de Huántar. Two columns — one of black limestone, one of white granite — flank the entrance stairway, giving the portal its name. Above the entrance, a carved lintel shows a row of raptorial birds (hawks or eagles). The columns are carved with supernatural figures in the Chavín style: fanged, with serpent hair and taloned feet. The black-and-white duality may represent complementary opposites (day/night, male/female) central to Andean cosmology. The stairway ascends between two facing walls also of contrasting stone."},
    {"title": "Nazca Underground Aqueducts (Puquios)", "location": "Nazca Valley, Ica, Peru", "culture": "Nazca", "region": "South America / Andes", "date_start": -200, "date_end": 600, "date_label": "~200 BCE+",
     "description": "Over 40 underground aqueducts (puquios) tapping subterranean water sources and channeling water to agricultural fields and reservoirs. Construction involved digging trenches, lining them with river cobbles without mortar, roofing with stone slabs and huarango wood beams, then backfilling. Spiral-shaped access wells (ojos — 'eyes') at intervals allow access for cleaning and ventilation — these spiraling ramps descend to the underground channel. Some puquios are still in use today. Total system length exceeds 30 km. The engineering solved water scarcity in one of the driest inhabited deserts on Earth."},
    {"title": "Tiwanaku Kalasasaya Temple", "location": "Tiwanaku, La Paz, Bolivia", "culture": "Tiwanaku", "region": "South America / Andes", "date_start": -300, "date_end": 700, "date_label": "~300 BCE+",
     "description": "A rectangular semi-subterranean platform (130 x 120 meters) with walls of upright sandstone pillars alternating with smaller stone infill blocks. The eastern wall contains the Gateway of the Sun — a single andesite block (3 x 4 meters, approximately 10 tons) carved with a central 'Staff God' figure (often identified as Viracocha) flanked by rows of running winged attendants. The Ponce Monolith (a carved standing figure 2.4 meters tall) stands inside the enclosure. Stone tenon heads once protruded from the walls. Solar alignments mark equinox and solstice sunrise positions through the gateway. Elevation: 3,850 meters."},
    {"title": "Tiwanaku Semi-Subterranean Temple", "location": "Tiwanaku, La Paz, Bolivia", "culture": "Tiwanaku", "region": "South America / Andes", "date_start": -300, "date_end": 700, "date_label": "~300 BCE+",
     "description": "A sunken rectangular court (28.5 x 26 meters, 2 meters below ground level) with walls studded with 175 carved stone tenon heads depicting different human faces — each face unique, possibly representing different ethnic groups or ancestors. The Bennett Monolith (the largest Tiwanaku stone sculpture, 7.3 meters tall, 20 tons) once stood at the center. Walls are constructed of sandstone pillars with smaller blocks fitted between them. A drainage system below the floor channels rainwater out through underground conduits. Accessed by a stairway on the south side."},

    # === AFRICA ===
    {"title": "Great Zimbabwe Dry-Stone Walls", "location": "Masvingo, Zimbabwe", "culture": "Kingdom of Zimbabwe (Shona)", "region": "Southern Africa", "date_start": 1100, "date_end": 1450, "date_label": "~1100 CE",
     "description": "The Great Enclosure is an elliptical stone wall structure — the outer wall is 244 meters in circumference, up to 11 meters tall and 5 meters thick at the base. Built entirely of shaped granite blocks laid without mortar in a technique unique to the Zimbabwe tradition. The walls taper from base to top and are topped with a chevron (herringbone) decorative frieze. Inside stands a conical tower (5.5 meters diameter, 9 meters tall) of solid stone — function unknown. The Hill Complex above contains additional enclosures. Over 300 similar structures exist across the Zimbabwe plateau. Population at peak: 10,000–20,000."},

    # === JORDAN ===
    {"title": "Petra Water Channel System", "location": "Petra, Jordan", "culture": "Nabataean", "region": "Levant / Near East", "date_start": -100, "date_end": 100, "date_label": "~100 BCE",
     "description": "A hydraulic engineering network supplying water to a desert city of 30,000 people. Features include dams across wadis (seasonal rivers), rock-cut channels along cliff faces, ceramic pipelines running through tunnels, cisterns carved into rock, and a nymphaeum (ornamental fountain) in the city center. The Siq (entrance canyon) has channels carved into both walls — one for fresh water supply, one for flash-flood diversion. Over 200 cisterns and reservoirs identified. The system collected, stored, and distributed rainwater and spring water across the 264-square-km site area."},
    {"title": "Petra Siq Entrance Canyon", "location": "Petra, Jordan", "culture": "Nabataean", "region": "Levant / Near East", "date_start": -100, "date_end": 100, "date_label": "~100 BCE",
     "description": "A narrow gorge (Siq) approximately 1.2 km long, 3–12 meters wide, with sandstone walls rising 80 meters on each side. The natural geological fissure was modified by the Nabataeans: the floor was paved, water channels were carved into both walls, niches for votive sculptures were cut into the rock, and a monumental arch (now collapsed) once spanned the entrance. The canyon walls display natural striations of red, orange, yellow, and purple sandstone. The Siq terminates dramatically with a framed view of Al-Khazneh (The Treasury) — a 40-meter-tall rock-cut facade with Corinthian columns."},

    # === OCEANIA ===
    {"title": "Nan Madol Canal Network", "location": "Pohnpei, Federated States of Micronesia", "culture": "Saudeleur Dynasty", "region": "Oceania / Micronesia", "date_start": -200, "date_end": 1500, "date_label": "~200 BCE+",
     "description": "A network of shallow canals and seawalls connecting and separating the 92 artificial islets of Nan Madol. Canals are typically 1–2 meters deep at high tide and 5–30 meters wide. Retaining walls of stacked basalt prismatic columns line the canal edges. Tidal flow through the channels provided natural water circulation and access by canoe — boats were the primary means of transportation between islets. The entire canal network covers approximately 75 hectares of reef flat. The engineering required moving an estimated 750,000 metric tons of basalt columnar stone."},

    # === PACIFIC ===
    {"title": "Easter Island Rano Raraku Quarry (Moai Carving Site)", "location": "Rapa Nui (Easter Island), Chile", "culture": "Rapa Nui", "region": "Oceania / Pacific", "date_start": 1200, "date_end": 1500, "date_label": "~1200 CE",
     "description": "A volcanic crater (tuff cone) serving as the quarry for approximately 95% of all moai statues. The outer slopes contain approximately 397 moai in various stages of completion — from initial outline carved into the rock face to nearly finished statues partially buried upright in sediment along the slopes. The largest unfinished moai ('El Gigante') is 21 meters long and would have weighed approximately 270 tons. Statues were carved from the compressed volcanic ash (tuff) using basalt hand picks (toki). Carving technique: the moai was roughed out on its back while still attached to the bedrock, then undercut and slid down the slope to an upright position for finishing."},

    # === PERU (INCA) ===
    {"title": "Sacsayhuamán Zigzag Walls", "location": "Cusco, Peru", "culture": "Inca", "region": "South America / Andes", "date_start": 1440, "date_end": 1530, "date_label": "~1400 CE",
     "description": "Three parallel zigzag walls of precisely fitted polygonal limestone and andesite blocks terracing up a hillside above Cusco. The lowest wall is the most massive — individual blocks weigh up to 120–200 tons (the largest weighs approximately 300 tons, standing 8.5 meters tall). Blocks have smoothly curved faces with precisely ground joints — no mortar used. The zigzag pattern creates 22 angles (salients and reentrants) along a 540-meter frontline. A chronicler reported 20,000–30,000 workers were employed for 60+ years. Many blocks have rounded bulges (bosses) left from handling. The upper walls use progressively smaller stones."},

    # === LEBANON ===
    {"title": "Baalbek Podium Blocks (Temple of Jupiter Foundation)", "location": "Baalbek, Bekaa Valley, Lebanon", "culture": "Roman (on earlier foundation)", "region": "Levant / Near East", "date_start": -100, "date_end": 60, "date_label": "~100 BCE+",
     "description": "The massive stone platform supporting the Temple of Jupiter at Heliopolis (Baalbek). The podium consists of multiple courses of precisely cut and fitted limestone blocks. The sixth course contains the Trilithon — three stones each measuring approximately 19 x 4.3 x 3.6 meters and weighing approximately 800 tons each. Below the Trilithon, a course of slightly smaller but still enormous blocks (approximately 300–400 tons each). The quarry 800 meters away contains the unfinished 'Stone of the Pregnant Woman' (approximately 1,000 tons) and an even larger block discovered in 2014 (approximately 1,650 tons — the largest worked stone in antiquity). The blocks are fitted without mortar with joints so tight a razor blade cannot be inserted."},
]


async def main():
    pool = await asyncpg.create_pool(
        host="localhost", port=5432, user="eden", password="eden", database="eden",
        min_size=1, max_size=5,
    )

    async with pool.acquire() as conn:
        ts_id = await conn.fetchval("SELECT id FROM trusted_sources WHERE slug = 'wikidata-artifacts'")
        if not ts_id:
            ts_id = await conn.fetchval("SELECT id FROM trusted_sources ORDER BY created_at LIMIT 1")
        log.info("Using trusted_source_id: %s", ts_id)

    inserted = 0
    skipped = 0
    errors = 0

    for art in ARTIFACTS:
        ext_id = f"visual-lib-{art['title'].lower().replace(' ', '-').replace('/', '-')[:80]}"
        r2_key = f"visual-library/{ext_id}.json"
        title = art["title"]

        text = f"{art['title']}\n\nLocation: {art['location']}\nCulture: {art['culture']}\nRegion: {art['region']}\nDate: {art['date_label']}\n\n{art['description']}"
        checksum = hashlib.sha256(text.encode()).hexdigest()
        byte_size = len(text.encode("utf-8"))

        async with pool.acquire() as conn:
            existing = await conn.fetchval("SELECT id FROM raw_objects WHERE external_id = $1", ext_id)
            if existing:
                log.info("  SKIP (exists): %s", title)
                skipped += 1
                continue

            try:
                meta = json.dumps({"region": art["region"], "date_label": art["date_label"], "artifact_type": "visual_reference"})
                tsv_text = f"{title} {art['culture']} {art['location']} {art.get('region', '')} {art['description']}"

                async with conn.transaction():
                    ro_id = await conn.fetchval("""
                        INSERT INTO raw_objects (id, trusted_source_id, external_id, source_url,
                                                 content_type, checksum, byte_size, r2_key, fetched_at)
                        VALUES (gen_random_uuid(), $1, $2, $3, 'application/json', $4, $5, $6, NOW())
                        ON CONFLICT (r2_key) DO NOTHING RETURNING id
                    """, ts_id, ext_id, f"https://eden.internal/visual-library/{ext_id}",
                        checksum, byte_size, r2_key)
                    if not ro_id:
                        log.info("  SKIP (r2_key conflict): %s", title)
                        skipped += 1
                        continue

                    sr_id = await conn.fetchval("""
                        INSERT INTO source_records (id, raw_object_id, trusted_source_id, canonical_title,
                                                    culture, language_family, origin_place_name,
                                                    source_category, provenance_status, record_status,
                                                    metadata_jsonb, tsv, created_at, updated_at)
                        VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, 'site_archive',
                                'verified', 'published', $7::jsonb, to_tsvector('english', $8),
                                NOW(), NOW())
                        RETURNING id
                    """, ro_id, ts_id, title, art["culture"], art.get("region", ""),
                        art["location"], meta, tsv_text)

                    await conn.execute("""
                        INSERT INTO source_versions (id, source_record_id, version_type, language,
                                                     is_preferred, copyright_status, text_extracted,
                                                     tsv, created_at, updated_at)
                        VALUES (gen_random_uuid(), $1, 'museum_description', 'English',
                                true, 'public_domain', $2,
                                setweight(to_tsvector('english', $3), 'A') || to_tsvector('english', $2),
                                NOW(), NOW())
                    """, sr_id, text, title)

                    if art.get("date_start"):
                        await conn.execute("""
                            INSERT INTO source_dates (id, source_record_id, date_type, date_start, date_end,
                                                      date_label, dating_method, dating_confidence,
                                                      created_at, updated_at)
                            VALUES (gen_random_uuid(), $1, 'object_creation', $2, $3, $4,
                                    'archaeological', 'approximate', NOW(), NOW())
                        """, sr_id, art["date_start"], art.get("date_end", art["date_start"]),
                            art["date_label"])

                log.info("  OK: %s (%s)", title, art["date_label"])
                inserted += 1
            except Exception as e:
                log.error("  ERROR on %s: %s", title, e)
                errors += 1

    await pool.close()
    log.info("Done! Inserted: %d, Skipped: %d, Errors: %d", inserted, skipped, errors)


if __name__ == "__main__":
    asyncio.run(main())
