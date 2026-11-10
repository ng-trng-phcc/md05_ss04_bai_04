package lab.rikkei.storex;

import java.util.Map;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@SpringBootApplication
@RestController
public class ProductService {
    private static final String SERVICE = "product-service";

    public static void main(String[] args) {
        SpringApplication.run(ProductService.class, args);
    }

    @GetMapping("/")
    public Map<String, Object> index(HttpServletRequest request) {
        return Map.of("service", SERVICE, "receivedPath", request.getRequestURI());
    }

    @GetMapping("/42")
    public Map<String, Object> product(HttpServletRequest request) {
        return Map.of("service", SERVICE, "receivedPath", request.getRequestURI(),
                "productId", 42, "name", "Demo Travel Mug");
    }

    @GetMapping("/health")
    public Map<String, Object> health(HttpServletRequest request) {
        return Map.of("service", SERVICE, "receivedPath", request.getRequestURI(), "status", "UP");
    }
}
