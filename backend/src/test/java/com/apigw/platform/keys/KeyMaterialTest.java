package com.apigw.platform.keys;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Base64;
import java.util.HashSet;
import java.util.Set;

import org.junit.jupiter.api.Test;

import com.apigw.platform.common.Env;

class KeyMaterialTest {

    @Test
    void keysCarry256BitsAndAreUnique() {
        Set<String> seen = new HashSet<>();
        for (int i = 0; i < 200; i++) {
            KeyMaterial k = KeyMaterial.generate(Env.SANDBOX);
            byte[] secret = Base64.getUrlDecoder().decode(k.plaintext().substring("agw_sbx_".length()));
            assertThat(secret).hasSize(32);
            assertThat(seen.add(k.plaintext())).isTrue();
        }
    }

    @Test
    void hashIsSha256HexAndToStringNeverLeaksTheKey() {
        KeyMaterial k = KeyMaterial.generate(Env.PRODUCTION);
        assertThat(k.plaintext()).startsWith("agw_prd_");
        assertThat(k.hash()).hasSize(64).matches("[0-9a-f]+").isEqualTo(KeyMaterial.sha256Hex(k.plaintext()));
        assertThat(k.toString()).doesNotContain(k.plaintext()).contains(k.masked());
        assertThat(KeyMaterial.sha256Hex("abc"))
                .isEqualTo("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    }
}
