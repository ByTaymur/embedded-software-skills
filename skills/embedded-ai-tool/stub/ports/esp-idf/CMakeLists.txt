idf_component_register(
    SRCS "eat_port_esp_idf.c" "../../eat_embed.c" "../../eat_link.c" "../../eat_stub_core.c"
    INCLUDE_DIRS "." "../.."
    REQUIRES esp_timer driver)
# Apply to eat_embed.c too: the definition, not just its declaration, needs placement.
target_compile_options(${COMPONENT_LIB} PRIVATE "-include" "${CMAKE_CURRENT_LIST_DIR}/eat_port_config.h")
# TODO(port): choose EAT_SCRATCH_BYTES and executable-memory linker/cache policy before RAM calls.
