"""Config for the WooCommerce-batch scraper.

Each entry is a merchant we auto-discovered as running a standard WooCommerce
theme with product-category URLs exposed in the site nav. Category URLs were
enumerated from each merchant's homepage on 2026-07-07 and mapped to
PriceKenya taxonomy leaves via slug keyword matching. When a merchant
customises their category slugs later, refresh this file with a re-discovery
pass rather than editing entries individually.

The batch scraper (scrapers/merchants/wc_batch.py) reads this dict and runs
each merchant sequentially through the shared fetch_woocommerce_category
helper — no per-merchant module needed.
"""

from __future__ import annotations

# merchant_slug → { meta: {...}, leaf_to_urls: { leaf: [url, ...] } }
WC_MERCHANTS: dict[str, dict] = {
    "fivestar-ke": {
        "meta": {"slug": "fivestar-ke", "name": "Fivestar Electronics", "base_url": "https://fivestar.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://fivestar.co.ke/product-category/accessories/headphones"],
            "blenders": ["https://fivestar.co.ke/product-category/kitchen-electronics/blender"],
            "cameras": ["https://fivestar.co.ke/product-category/cameras", "https://fivestar.co.ke/product-category/cameras/xiaomi-cameras"],
            "cooking": ["https://fivestar.co.ke/product-category/kitchen-electronics/cooker", "https://fivestar.co.ke/product-category/kitchen-electronics/microwaves"],
            "laptops": ["https://fivestar.co.ke/product-category/laptops", "https://fivestar.co.ke/product-category/laptops/lenovo-laptops"],
            "phone-tablet-accessories": ["https://fivestar.co.ke/product-category/accessories"],
            "phones": ["https://fivestar.co.ke/product-category/smartphones", "https://fivestar.co.ke/product-category/smartphones/mobile-phones"],
            "refrigerators": ["https://fivestar.co.ke/product-category/kitchen-electronics/chest-freezers", "https://fivestar.co.ke/product-category/kitchen-electronics/fridge", "https://fivestar.co.ke/product-category/kitchen-electronics/showcase-fridges"],
            "tablets": ["https://fivestar.co.ke/product-category/smartphones/kids-tablets", "https://fivestar.co.ke/product-category/smartphones/tablet"],
            "tvs": ["https://fivestar.co.ke/product-category/accessories/tv", "https://fivestar.co.ke/product-category/smart-tvs", "https://fivestar.co.ke/product-category/smart-tvs/samsung-smart-tvs"],
            "washers-dryers": ["https://fivestar.co.ke/product-category/dryers", "https://fivestar.co.ke/product-category/dryers/hisense-dryers", "https://fivestar.co.ke/product-category/dryers/samsung-dryers"],
        },
    },
    "le-ke": {
        "meta": {"slug": "le-ke", "name": "LE Kenya", "base_url": "https://le.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://le.co.ke/product-category/earphones-and-headphones"],
            "cooking": ["https://le.co.ke/product-category/home-appliances/cookers"],
            "laptops": ["https://le.co.ke/product-category/computers-laptops"],
            "phone-tablet-accessories": ["https://le.co.ke/product-category/cameras-accessories", "https://le.co.ke/product-category/electronic-accessories", "https://le.co.ke/product-category/electronic-accessories/accessories"],
            "refrigerators": ["https://le.co.ke/product-category/fridges-freezers"],
            "tablets": ["https://le.co.ke/product-category/phones-tablets"],
            "tvs": ["https://le.co.ke/product-category/smart-digital-tvs"],
        },
    },
    "finetech-ke": {
        "meta": {"slug": "finetech-ke", "name": "Finetech", "base_url": "https://finetech.co.ke"},
        "leaf_to_urls": {
            "laptops": ["https://finetech.co.ke/product-category/computers-tablets"],
            "phone-tablet-accessories": ["https://finetech.co.ke/product-category/accessories"],
            "phones": ["https://finetech.co.ke/product-category/phones", "https://finetech.co.ke/product-category/phones/iphone", "https://finetech.co.ke/product-category/smartphones"],
        },
    },
    "dixons-ke": {
        "meta": {"slug": "dixons-ke", "name": "Dixons", "base_url": "https://www.dixons.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://www.dixons.co.ke/product-category/mobiles/earphones-headphones"],
            "cameras": ["https://www.dixons.co.ke/product-category/cameras", "https://www.dixons.co.ke/product-category/cameras/digital-cameras", "https://www.dixons.co.ke/product-category/cameras/professional-cameras"],
            "cooking": ["https://www.dixons.co.ke/product-category/cookers-ovens/free-standing-cookers", "https://www.dixons.co.ke/product-category/cookers-ovens/microwave-ovens", "https://www.dixons.co.ke/product-category/cookers-ovens/ovens"],
            "laptops": ["https://www.dixons.co.ke/product-category/computing/laptops"],
            "phone-tablet-accessories": ["https://www.dixons.co.ke/product-category/electronics/accessories", "https://www.dixons.co.ke/product-category/fridges-freezers/accessories-fridges-freezers", "https://www.dixons.co.ke/product-category/kitchen-appliances/accessories-kitchen-appliances"],
            "phones": ["https://www.dixons.co.ke/product-category/mobiles/feature-phones", "https://www.dixons.co.ke/product-category/mobiles/smart-phones"],
            "refrigerators": ["https://www.dixons.co.ke/product-category/fridges-freezers", "https://www.dixons.co.ke/product-category/fridges-freezers/freezers", "https://www.dixons.co.ke/product-category/fridges-freezers/fridges"],
            "tablets": ["https://www.dixons.co.ke/product-category/mobiles/tablets"],
            "tvs": ["https://www.dixons.co.ke/product-category/electronics/televisions"],
            "washers-dryers": ["https://www.dixons.co.ke/product-category/washers-dryers/dishwasher", "https://www.dixons.co.ke/product-category/washers-dryers/dryers", "https://www.dixons.co.ke/product-category/washers-dryers/washing-machines"],
        },
    },
    "techonline-ke": {
        "meta": {"slug": "techonline-ke", "name": "TechOnline", "base_url": "https://techonline.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://techonline.co.ke/product-category/sound-system/party-speaker", "https://techonline.co.ke/product-category/sound-system/soundbar"],
            "blenders": ["https://techonline.co.ke/product-category/blenders"],
            "cameras": ["https://techonline.co.ke/product-category/accessories/cameras"],
            "cooking": ["https://techonline.co.ke/product-category/built-in-appliances/built-in-gas-hob", "https://techonline.co.ke/product-category/built-in-appliances/built-in-microwave", "https://techonline.co.ke/product-category/built-in-appliances/built-in-oven"],
            "ironing-laundry": ["https://techonline.co.ke/product-category/iron"],
            "phone-tablet-accessories": ["https://techonline.co.ke/product-category/accessories"],
            "refrigerators": ["https://techonline.co.ke/product-category/freezer", "https://techonline.co.ke/product-category/fridge"],
            "tvs": ["https://techonline.co.ke/product-category/smart-tvs", "https://techonline.co.ke/product-category/smart_tvs"],
            "washers-dryers": ["https://techonline.co.ke/product-category/dryer", "https://techonline.co.ke/product-category/washing-machines"],
        },
    },
    "jojabo-ke": {
        "meta": {"slug": "jojabo-ke", "name": "Jojabo Technologies", "base_url": "https://jojabotechnologies.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://jojabotechnologies.co.ke/product-category/audio-mixer", "https://jojabotechnologies.co.ke/product-category/bass-speakers", "https://jojabotechnologies.co.ke/product-category/earbuds"],
            "cameras": ["https://jojabotechnologies.co.ke/product-category/camera", "https://jojabotechnologies.co.ke/product-category/cctv-cameras"],
            "console-accessories": ["https://jojabotechnologies.co.ke/product-category/acoustics-gaming-headsets", "https://jojabotechnologies.co.ke/product-category/gaming-headsets"],
            "laptops": ["https://jojabotechnologies.co.ke/product-category/computer-accessories", "https://jojabotechnologies.co.ke/product-category/computer-accessories-laptops", "https://jojabotechnologies.co.ke/product-category/gaming-laptops"],
            "peripherals-accessories": ["https://jojabotechnologies.co.ke/product-category/gaming-keyboards", "https://jojabotechnologies.co.ke/product-category/keyboards", "https://jojabotechnologies.co.ke/product-category/mouse"],
            "phone-tablet-accessories": ["https://jojabotechnologies.co.ke/product-category/phone-accessories"],
            "phones": ["https://jojabotechnologies.co.ke/product-category/phones"],
            "tablets": ["https://jojabotechnologies.co.ke/product-category/deal-of-the-week-hot-sale-tablets", "https://jojabotechnologies.co.ke/product-category/ipad", "https://jojabotechnologies.co.ke/product-category/ipad-tablets"],
            "tvs": ["https://jojabotechnologies.co.ke/product-category/gaming-tv-sound-systems", "https://jojabotechnologies.co.ke/product-category/tv-sound-systems"],
        },
    },
    "tclke-ke": {
        "meta": {"slug": "tclke-ke", "name": "TCL Kenya", "base_url": "https://tclke.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://tclke.co.ke/product-category/jbl/jbl-earbuds", "https://tclke.co.ke/product-category/jbl/jbl-headphones", "https://tclke.co.ke/product-category/jbl/jbl-portable-speakers"],
            "cooking": ["https://tclke.co.ke/product-category/scl/scl-cookers"],
            "phone-tablet-accessories": ["https://tclke.co.ke/product-category/accessories"],
            "refrigerators": ["https://tclke.co.ke/product-category/scl/scl-freezers", "https://tclke.co.ke/product-category/scl/scl-fridges", "https://tclke.co.ke/product-category/tcl-refrigerators"],
            "tvs": ["https://tclke.co.ke/product-category/tcl-tvs", "https://tclke.co.ke/product-category/tcl-tvs/tcl-tvs-by-size", "https://tclke.co.ke/product-category/tcl-tvs/tv-by-feature"],
            "washers-dryers": ["https://tclke.co.ke/product-category/scl/scl-washing-machines", "https://tclke.co.ke/product-category/tcl-washing-machines", "https://tclke.co.ke/product-category/washing-machines"],
        },
    },
    "megatech-ke": {
        "meta": {"slug": "megatech-ke", "name": "Megatech Electronics", "base_url": "https://megatechelectronics.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://megatechelectronics.co.ke/product-category/audio", "https://megatechelectronics.co.ke/product-category/audio/earbuds-audio", "https://megatechelectronics.co.ke/product-category/audio/earphones"],
            "cameras": ["https://megatechelectronics.co.ke/product-category/cameras", "https://megatechelectronics.co.ke/product-category/cameras/insta-cameras"],
            "console-accessories": ["https://megatechelectronics.co.ke/product-category/gaming/controllers", "https://megatechelectronics.co.ke/product-category/gaming/accessories-gaming", "https://megatechelectronics.co.ke/product-category/gaming/headsets-gaming"],
            "phone-tablet-accessories": ["https://megatechelectronics.co.ke/product-category/accessories", "https://megatechelectronics.co.ke/product-category/accessories/car-chargers", "https://megatechelectronics.co.ke/product-category/accessories/chargers"],
            "phones": ["https://megatechelectronics.co.ke/product-category/audio/microphones", "https://megatechelectronics.co.ke/product-category/smartphones", "https://megatechelectronics.co.ke/product-category/smartphones/iphone"],
            "tablets": ["https://megatechelectronics.co.ke/product-category/tablets", "https://megatechelectronics.co.ke/product-category/tablets/infinix-tablet", "https://megatechelectronics.co.ke/product-category/tablets/oppo-tablets"],
        },
    },
    "zurimall-ke": {
        "meta": {"slug": "zurimall-ke", "name": "Zurimall", "base_url": "https://zurimall.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://zurimall.co.ke/product-category/tvs-hometheaters/soundbars"],
            "cameras": ["https://zurimall.co.ke/product-category/accessories/cameras", "https://zurimall.co.ke/product-category/accessories/cctv-cameras"],
            "laptops": ["https://zurimall.co.ke/product-category/all-laptops", "https://zurimall.co.ke/product-category/all-laptops-filters", "https://zurimall.co.ke/product-category/all-laptops-prices-filter", "https://zurimall.co.ke/product-category/accessories/gaming"],
            "phone-tablet-accessories": ["https://zurimall.co.ke/product-category/accessories", "https://zurimall.co.ke/product-category/accessories/networking-cables"],
            "phones": ["https://zurimall.co.ke/product-category/iphones", "https://zurimall.co.ke/product-category/phones", "https://zurimall.co.ke/product-category/phones/iphone"],
            "tvs": ["https://zurimall.co.ke/product-category/tvs-hometheaters", "https://zurimall.co.ke/product-category/tvs-hometheaters/hisense-tvs", "https://zurimall.co.ke/product-category/tvs-hometheaters/lg-tvs"],
        },
    },
    "pixels-ke": {
        "meta": {"slug": "pixels-ke", "name": "Pixels Electronics", "base_url": "https://pixelselectronics.co.ke"},
        "leaf_to_urls": {
            "cameras": ["https://pixelselectronics.co.ke/product-category/photo-video/cameras-drones"],
            "laptops": ["https://pixelselectronics.co.ke/product-category/computer-office", "https://pixelselectronics.co.ke/product-category/laptops-tablets-pcs/laptops", "https://pixelselectronics.co.ke/product-category/laptops/apple-macbook", "https://pixelselectronics.co.ke/product-category/laptops-tablets-pcs/laptops/gaming-laptop"],
            "phones": ["https://pixelselectronics.co.ke/product-category/cell-phones-accessories/cell-phones", "https://pixelselectronics.co.ke/product-category/smartphones", "https://pixelselectronics.co.ke/product-category/smartphones/mobile-phones"],
            "tablets": ["https://pixelselectronics.co.ke/product-category/laptops-tablets-pcs", "https://pixelselectronics.co.ke/product-category/laptops-tablets-pcs/tablets", "https://pixelselectronics.co.ke/product-category/tablets/apple-ipad"],
        },
    },
    "quest-ke": {
        "meta": {"slug": "quest-ke", "name": "Quest Appliances", "base_url": "https://www.questappliances.com"},
        "leaf_to_urls": {
            "audio": ["https://www.questappliances.com/product-category/televisions-audio/portable-speakers", "https://www.questappliances.com/product-category/televisions-audio/speakers-sound-systems"],
            "blenders": ["https://www.questappliances.com/product-category/home-appliances/blenders-juicers"],
            "cooking": ["https://www.questappliances.com/product-category/home-appliances/microwaves", "https://www.questappliances.com/product-category/home-appliances/pressure-cooker", "https://www.questappliances.com/product-category/home-appliances/standing-cookers"],
            "ironing-laundry": ["https://www.questappliances.com/product-category/home-appliances/garment-steamer", "https://www.questappliances.com/product-category/home-appliances/irons"],
            "kettles": ["https://www.questappliances.com/product-category/home-appliances/kettles"],
            "phone-tablet-accessories": ["https://www.questappliances.com/product-category/accessories", "https://www.questappliances.com/product-category/accessories/cables", "https://www.questappliances.com/product-category/personal-care/hair-accessories"],
            "phones": ["https://www.questappliances.com/product-category/smartphone"],
            "refrigerators": ["https://www.questappliances.com/product-category/home-appliances/refrigerators-freezers"],
            "tablets": ["https://www.questappliances.com/product-category/home-appliances/tabletop-cookers"],
            "toasters": ["https://www.questappliances.com/product-category/home-appliances/toasters-sandwich-makers"],
            "tvs": ["https://www.questappliances.com/product-category/televisions-audio", "https://www.questappliances.com/product-category/televisions-audio/cameras-televisions-audio", "https://www.questappliances.com/product-category/televisions-audio/digital-tvs"],
            "washers-dryers": ["https://www.questappliances.com/product-category/home-appliances/washing-machine"],
        },
    },
    "smartdevices-ke": {
        "meta": {"slug": "smartdevices-ke", "name": "Smart Devices Kenya", "base_url": "https://www.smartdeviceskenya.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://www.smartdeviceskenya.co.ke/product-category/audio", "https://www.smartdeviceskenya.co.ke/product-category/audio/soundbars", "https://www.smartdeviceskenya.co.ke/product-category/tv-audio"],
            "cooking": ["https://www.smartdeviceskenya.co.ke/product-category/home-appliances/cookers", "https://www.smartdeviceskenya.co.ke/product-category/home-appliances/microwaves"],
            "inverters": ["https://www.smartdeviceskenya.co.ke/product-category/inverters"],
            "solar-panels": ["https://www.smartdeviceskenya.co.ke/product-category/solar-panels"],
            "solar-batteries": ["https://www.smartdeviceskenya.co.ke/product-category/solar-batteries"],
            "laptops": ["https://www.smartdeviceskenya.co.ke/product-category/computers-printers/computer-desktops", "https://www.smartdeviceskenya.co.ke/product-category/computers-printers/laptops"],
            "phone-tablet-accessories": ["https://www.smartdeviceskenya.co.ke/product-category/power-banks"],
            "phones": ["https://www.smartdeviceskenya.co.ke/product-category/smartphones", "https://www.smartdeviceskenya.co.ke/product-category/smartphones/apple-iphones", "https://www.smartdeviceskenya.co.ke/product-category/smartphones/google-pixel-phones"],
            "refrigerators": ["https://www.smartdeviceskenya.co.ke/product-category/home-appliances/fridges"],
            "tablets": ["https://www.smartdeviceskenya.co.ke/product-category/laptops-tablets-pcs"],
            "tvs": ["https://www.smartdeviceskenya.co.ke/product-category/televisions"],
            "washers-dryers": ["https://www.smartdeviceskenya.co.ke/product-category/home-appliances/washing-machines"],
        },
    },
    "smartphoneskenya-ke": {
        "meta": {"slug": "smartphoneskenya-ke", "name": "Smartphones Kenya", "base_url": "https://smartphoneskenya.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://smartphoneskenya.co.ke/product-category/soundbar"],
            "laptops": ["https://smartphoneskenya.co.ke/product-category/computers", "https://smartphoneskenya.co.ke/product-category/computers/laptops"],
            "phone-tablet-accessories": ["https://smartphoneskenya.co.ke/product-category/phones-in-kenya/accessories-phones-in-kenya"],
            "phones": ["https://smartphoneskenya.co.ke/product-category/phones-in-kenya", "https://smartphoneskenya.co.ke/product-category/phones-in-kenya/infinix-phones", "https://smartphoneskenya.co.ke/product-category/phones-in-kenya/iphones"],
            "tablets": ["https://smartphoneskenya.co.ke/product-category/tablets-in-kenya/kids-tablets"],
            "tvs": ["https://smartphoneskenya.co.ke/product-category/televisions"],
        },
    },
    "patabay-ke": {
        "meta": {"slug": "patabay-ke", "name": "Patabay Kenya", "base_url": "https://patabay.co.ke"},
        "leaf_to_urls": {
            "laptops": ["https://patabay.co.ke/product-category/office-appliances/laptop"],
            "phones": ["https://patabay.co.ke/product-category/phones-and-tablets/smartphones"],
            "refrigerators": ["https://patabay.co.ke/product-category/tcl-refrigerators"],
            "solar-panels": ["https://patabay.co.ke/product-category/home-appliances/solar"],
            "tablets": ["https://patabay.co.ke/product-category/kids-tablets-in-kenya", "https://patabay.co.ke/product-category/phones-and-tablets/tablets"],
            "tvs": ["https://patabay.co.ke/product-category/televisions-and-entertainment/televisions", "https://patabay.co.ke/product-category/televisions-2"],
        },
    },
    "zuka-ke": {
        "meta": {"slug": "zuka-ke", "name": "Zuka Electronics", "base_url": "https://zuka.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://zuka.co.ke/product-category/sound-systems/bluetooth-speakers"],
            "blenders": ["https://zuka.co.ke/product-category/blenders"],
            "cooking": ["https://zuka.co.ke/product-category/cookers", "https://zuka.co.ke/product-category/hobs", "https://zuka.co.ke/product-category/in-built-cookers"],
            "phone-tablet-accessories": ["https://zuka.co.ke/product-category/accessories"],
            "phones": ["https://zuka.co.ke/product-category/mobile-phones"],
            # showcase-chillers is a display fridge category despite the "case" substring
            # tripping the accessories keyword — route to refrigerators.
            "refrigerators": ["https://zuka.co.ke/product-category/freezer", "https://zuka.co.ke/product-category/showcase-chillers"],
            "tvs": ["https://zuka.co.ke/product-category/televisions"],
            "washers-dryers": ["https://zuka.co.ke/product-category/washing-machines"],
        },
    },
    "techstore-ke": {
        "meta": {"slug": "techstore-ke", "name": "Tech Store Kenya", "base_url": "https://techstore.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://techstore.co.ke/product-category/headphones"],
            "cameras": ["https://techstore.co.ke/product-category/drones"],
            "phone-tablet-accessories": ["https://techstore.co.ke/product-category/mobile/accessories", "https://techstore.co.ke/product-category/watches"],
            "phones": ["https://techstore.co.ke/product-category/mobile/mobiles"],
            "tablets": ["https://techstore.co.ke/product-category/mobile/tablets"],
        },
    },
    "devicestech-ke": {
        "meta": {"slug": "devicestech-ke", "name": "Devices Technology Store", "base_url": "https://www.devicestech.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://www.devicestech.co.ke/product-category/computer-accessories/audio-speakers", "https://www.devicestech.co.ke/product-category/computer-accessories/earphones", "https://www.devicestech.co.ke/product-category/computer-accessories/headphones"],
            "cameras": ["https://www.devicestech.co.ke/product-category/cctv-cameras/hd-cameras", "https://www.devicestech.co.ke/product-category/cctv-cameras/ip-cameras"],
            "laptops": ["https://www.devicestech.co.ke/product-category/computer-accessories/docking-stations-computer-accessories"],
            "peripherals-accessories": ["https://www.devicestech.co.ke/product-category/computer-accessories/keyboards", "https://www.devicestech.co.ke/product-category/computer-accessories/mouse", "https://www.devicestech.co.ke/product-category/computer-accessories/usb-hub"],
            "phone-tablet-accessories": ["https://www.devicestech.co.ke/product-category/computer-accessories/cables", "https://www.devicestech.co.ke/product-category/computer-accessories/laptop-chargers"],
            "tablets": ["https://www.devicestech.co.ke/product-category/tablets"],
            "tvs": ["https://www.devicestech.co.ke/product-category/tvs"],
        },
    },
    "nairobilaptops-ke": {
        "meta": {"slug": "nairobilaptops-ke", "name": "Nairobi Laptops", "base_url": "https://nairobilaptops.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://nairobilaptops.co.ke/product-category/soundbars"],
            "cameras": ["https://nairobilaptops.co.ke/product-category/camera", "https://nairobilaptops.co.ke/product-category/cctv"],
            "laptops": ["https://nairobilaptops.co.ke/product-category/desktops", "https://nairobilaptops.co.ke/product-category/laptops"],
            "phones": ["https://nairobilaptops.co.ke/product-category/phones"],
            "tvs": ["https://nairobilaptops.co.ke/product-category/televisions"],
        },
    },
    "solarshop-ke": {
        "meta": {"slug": "solarshop-ke", "name": "SolarShop Africa", "base_url": "https://solarshop.co.ke"},
        # Solar-focused specialist. Dropping /solar-charge-controllers/ URLs
        # (my keyword discovery routed them to console-accessories because
        # "controller" is in the leaf keyword — that's for PS5/Xbox pads,
        # not power electronics; no matcher covers charge controllers yet).
        # Also dropping /solar-dc-cables-accessories/ and outdoor-lights.
        "leaf_to_urls": {
            "inverters": ["https://solarshop.co.ke/product-category/solar-inverters"],
            "solar-batteries": ["https://solarshop.co.ke/product-category/solar-batteries", "https://solarshop.co.ke/product-category/solar-batteries/lithium-ion-batteries"],
        },
    },
    "solarstore-ke": {
        "meta": {"slug": "solarstore-ke", "name": "Solar Store East Africa", "base_url": "https://solarstore.co.ke"},
        "leaf_to_urls": {
            "inverters": ["https://solarstore.co.ke/product-category/solar-inverters", "https://solarstore.co.ke/product-category/solar-inverters/hybrid-inverters"],
        },
    },
    "sollatek-ke": {
        "meta": {"slug": "sollatek-ke", "name": "Sollatek", "base_url": "https://sollatek.co.ke"},
        # Same charge-controller / cables cleanup as solarshop.
        "leaf_to_urls": {
            "inverters": ["https://sollatek.co.ke/product-category/solar-systems-appliances/inverter"],
            "solar-batteries": ["https://sollatek.co.ke/product-category/solar-systems-appliances/solar-batteries"],
        },
    },
    "nairobitvshop-ke": {
        "meta": {"slug": "nairobitvshop-ke", "name": "Nairobi TV Shop", "base_url": "https://nairobitvshop.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://nairobitvshop.co.ke/product-category/headphones", "https://nairobitvshop.co.ke/product-category/portable-speakers", "https://nairobitvshop.co.ke/product-category/soundbars"],
            "laptops": ["https://nairobitvshop.co.ke/product-category/laptops-desktops"],
            "phone-tablet-accessories": ["https://nairobitvshop.co.ke/product-category/accessories"],
            "tvs": ["https://nairobitvshop.co.ke/product-category/television", "https://nairobitvshop.co.ke/product-category/tv-mounts"],
        },
    },
}
